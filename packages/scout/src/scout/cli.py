import asyncio
import json
import os
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Annotated

import boto3
import typer
from dotenv import load_dotenv
from langchain_aws import __version__ as langchain_aws_version
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import ValidationError

from scout import store
from scout.config import Settings
from scout.graph import build_graph, make_slug
from scout.llm import make_llm
from scout.mcp_client import make_mcp_client

app = typer.Typer()

# 파이프라인 6단계 전체 이름. 아직 구현된 노드만 IMPLEMENTED_STAGES에 있다 — STEP이 끝날 때마다 하나씩 늘어난다.
STAGE_ORDER = ["interview", "analyze", "search", "verify", "evaluate", "report"]
IMPLEMENTED_STAGES = ["interview", "analyze"]


class ShowStage(str, Enum):
    interview = "interview"
    analyze = "analyze"
    search = "search"
    verify = "verify"
    evaluate = "evaluate"


class Stage(str, Enum):
    interview = "interview"
    analyze = "analyze"
    search = "search"
    verify = "verify"
    evaluate = "evaluate"
    report = "report"


@app.callback()
def callback() -> None:
    """project-scout — 만들고 싶은 소프트웨어를 근거와 함께 답하는 CLI."""
    # boto3는 .env를 모른다 — os.environ에 직접 있어야 AWS_ACCESS_KEY_ID 등을 집는다.
    # pydantic-settings의 env_file 로딩은 Settings 필드에만 값을 채우고 os.environ은 건드리지 않는다.
    load_dotenv()


@app.command()
def doctor() -> None:
    """AWS 자격·리전·모델·동시쿼터·MCP 스모크를 확인한다."""
    asyncio.run(_doctor())


async def _doctor() -> None:
    typer.echo("== scout doctor ==")

    try:
        settings = Settings()
    except ValidationError as e:
        typer.echo(
            f"[FAIL] Settings 로딩 실패 — 필수 변수(AWS_DEFAULT_REGION 등)를 확인하세요:\n{e}"
        )
        raise typer.Exit(code=1) from None

    typer.echo(f"[OK] AWS_DEFAULT_REGION={settings.aws_region}")

    has_key = bool(os.environ.get("AWS_ACCESS_KEY_ID")) and bool(
        os.environ.get("AWS_SECRET_ACCESS_KEY")
    )
    typer.echo(
        f"AWS Access Key: {'설정됨' if has_key else '미설정'} (값은 출력하지 않음)"
    )
    typer.echo(f"boto3: {boto3.__version__}")
    typer.echo(f"langchain-aws: {langchain_aws_version}")

    session = boto3.Session(region_name=settings.aws_region)

    try:
        identity = session.client("sts").get_caller_identity()
        typer.echo(f"[OK] sts get-caller-identity: {identity['Arn']}")
    except Exception as e:  # noqa: BLE001 — doctor는 원인 불문 다음 확인으로 넘어가야 한다
        typer.echo(f"[SKIP] AWS 인증 확인 실패 — {e}")
        typer.echo(
            "      .env 의 AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY 를 채운 뒤 다시 실행하세요."
        )
        await _mcp_smoke()
        return

    try:
        models = session.client("bedrock").list_foundation_models()
        matches = sorted(
            m["modelId"]
            for m in models["modelSummaries"]
            if "sonnet" in m["modelId"].lower()
        )
        typer.echo(f"[OK] ListFoundationModels — sonnet 계열 모델 {len(matches)}개")
        for model_id in matches[:5]:
            typer.echo(f"      {model_id}")
    except Exception as e:  # noqa: BLE001 — doctor는 원인 불문 다음 확인으로 넘어가야 한다
        typer.echo(f"[FAIL] ListFoundationModels 실패: {e}")

    try:
        llm = make_llm(settings)
        result = await llm.ainvoke("ping")
        typer.echo(f"[OK] Sonnet 1회 호출 성공 ({len(str(result.content))} chars)")

        results = await asyncio.gather(*[llm.ainvoke("ping") for _ in range(4)])
        typer.echo(
            f"[OK] Sonnet 4병렬 호출 성공 ({len(results)}개 응답, 동시 쿼터 확인됨)"
        )
    except Exception as e:  # noqa: BLE001 — doctor는 원인 불문 다음 확인으로 넘어가야 한다
        typer.echo(f"[FAIL] Bedrock 호출 실패: {e}")

    await _mcp_smoke()


async def _mcp_smoke() -> None:
    try:
        client = make_mcp_client()
        tools = await client.get_tools()
        tool_map = {t.name: t for t in tools}
        result = await tool_map["npm_package"].ainvoke({"name": "socket.io"})
        typer.echo(
            f"[OK] MCP npm_package(socket.io) 응답 수신 ({len(str(result))} chars)"
        )
    except Exception as e:  # noqa: BLE001 — doctor는 원인 불문 다음 확인으로 넘어가야 한다
        typer.echo(f"[FAIL] MCP 스모크 실패: {e}")


@app.command()
def run(
    description: str,
    from_stage: Annotated[
        Stage, typer.Option("--from", help="이 단계부터 실행한다")
    ] = Stage.interview,
    stop_after: Annotated[
        Stage | None, typer.Option("--stop-after", help="이 단계까지만 실행한다")
    ] = None,
    max_components: Annotated[int | None, typer.Option("--max-components")] = None,
    max_candidates: Annotated[int | None, typer.Option("--max-candidates")] = None,
) -> None:
    """설명 한 줄로 파이프라인을 실행한다. interview부터 시작해 되묻고 runs에 저장한다."""
    for stage in (from_stage, stop_after):
        if stage is not None and stage.value not in IMPLEMENTED_STAGES:
            typer.echo(
                f"[미구현] '{stage.value}' 단계는 아직 없다 — "
                f"지금 구현된 단계: {', '.join(IMPLEMENTED_STAGES)}"
            )
            raise typer.Exit(code=1)

    try:
        settings = Settings()
    except ValidationError as e:
        typer.echo(f"[FAIL] Settings 로딩 실패 — 필수 변수를 확인하세요:\n{e}")
        raise typer.Exit(code=1) from None

    if max_components is not None:
        settings.scout_max_components = max_components
    if max_candidates is not None:
        settings.scout_max_candidates = max_candidates

    slug = make_slug(description, today=datetime.now(UTC).date().isoformat())
    llm = make_llm(settings)

    checkpoint_path = f"{settings.scout_runs_dir}/{slug}/checkpoints.sqlite"
    Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)

    initial_state = {
        "slug": slug,
        "description": description,
        "max_components": settings.scout_max_components,
        "max_candidates": settings.scout_max_candidates,
    }
    with SqliteSaver.from_conn_string(checkpoint_path) as checkpointer:
        graph = build_graph(llm, checkpointer)
        result = graph.invoke(
            initial_state, config={"configurable": {"thread_id": slug}}
        )

    typer.echo(f"\n[OK] slug={slug}")
    typer.echo(
        json.dumps(result["interview"].model_dump(), ensure_ascii=False, indent=2)
    )
    if "components" in result:
        typer.echo(
            "\n[components] (search로 통과된 요소 — 걸러진 것은 show analyze로 확인)"
        )
        typer.echo(
            json.dumps(
                [c.model_dump() for c in result["components"]],
                ensure_ascii=False,
                indent=2,
            )
        )


@app.command()
def show(slug: str, stage: ShowStage) -> None:
    """해당 단계가 쓴 테이블을 JSON으로 stdout에 덤프한다. 03-저장.md의 단계↔테이블 매핑을 따른다."""
    result: object
    if stage is ShowStage.interview:
        result = store.get_run(slug)
    elif stage is ShowStage.analyze:
        result = [c.model_dump() for c in store.get_components(slug)]
    elif stage is ShowStage.search:
        result = {
            "candidates": [c.model_dump() for c in store.get_candidates(slug)],
        }
    elif stage is ShowStage.verify:
        result = [v.model_dump() for v in store.get_verdicts(slug)]
    else:  # evaluate
        result = {
            "scores": store.get_scores(slug),
            "picks": store.get_picks(slug),
        }

    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
