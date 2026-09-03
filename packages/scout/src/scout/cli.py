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
from scout.stages import search as search_stage

app = typer.Typer()

# 파이프라인 6단계 전체 이름. 아직 구현된 노드만 IMPLEMENTED_STAGES에 있다 — STEP이 끝날 때마다 하나씩 늘어난다.
STAGE_ORDER = ["interview", "analyze", "search", "verify", "evaluate", "report"]
IMPLEMENTED_STAGES = ["interview", "analyze", "search"]
STAGE_LABELS = {
    "interview": "인터뷰",
    "analyze": "분석",
    "search": "검색",
    "verify": "검증",
    "evaluate": "평가",
    "report": "리포트",
}


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


@app.callback(invoke_without_command=True)
def callback(ctx: typer.Context) -> None:
    """project-scout — 만들고 싶은 소프트웨어를 근거와 함께 답하는 CLI."""
    # boto3는 .env를 모른다 — os.environ에 직접 있어야 AWS_ACCESS_KEY_ID 등을 집는다.
    # pydantic-settings의 env_file 로딩은 Settings 필드에만 값을 채우고 os.environ은 건드리지 않는다.
    load_dotenv()
    if ctx.invoked_subcommand is None:
        # 기본 진입점 — 설명은 대화형으로 받는다 (02-파이프라인.md "실행 흐름").
        _run_pipeline(None, Stage.interview, None, None, None)


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
    description: Annotated[str | None, typer.Argument()] = None,
    from_stage: Annotated[
        Stage, typer.Option("--from", help="이 단계부터 실행한다")
    ] = Stage.interview,
    stop_after: Annotated[
        Stage | None, typer.Option("--stop-after", help="이 단계까지만 실행한다")
    ] = None,
    max_components: Annotated[int | None, typer.Option("--max-components")] = None,
    max_candidates: Annotated[int | None, typer.Option("--max-candidates")] = None,
    auto_approve_search: Annotated[
        bool,
        typer.Option(
            "--auto-approve-search",
            help="웹검색 승인을 자동으로 통과시킨다 (비대화형 재현용)",
        ),
    ] = False,
) -> None:
    """파이프라인을 실행한다. 설명을 인자로 안 주면 대화형으로 묻는다 (개발용 —
    `--from`/`--stop-after`/`--max-components`/`--max-candidates`로 재현·재개한다).
    """
    _run_pipeline(
        description,
        from_stage,
        stop_after,
        max_components,
        max_candidates,
        auto_approve_search=auto_approve_search,
    )


def _run_pipeline(
    description: str | None,
    from_stage: Stage,
    stop_after: Stage | None,
    max_components: int | None,
    max_candidates: int | None,
    *,
    auto_approve_search: bool = False,
) -> None:
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

    if description is None:
        description = typer.prompt("프로젝트 설명 입력")

    slug = make_slug(description, today=datetime.now(UTC).date().isoformat())
    llm = make_llm(settings)

    checkpoint_path = f"{settings.scout_runs_dir}/{slug}/checkpoints.sqlite"
    Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)

    initial_state = {
        "slug": slug,
        "description": description,
        "max_components": settings.scout_max_components,
        "max_candidates": settings.scout_max_candidates,
        "max_turns": settings.scout_interview_max_turns,
    }

    typer.echo(f"\n[{STAGE_LABELS['interview']}] 단계를 시작합니다.")
    stopped_early = False
    approve = (
        search_stage.auto_approve
        if auto_approve_search
        else search_stage.default_approve
    )
    with SqliteSaver.from_conn_string(checkpoint_path) as checkpointer:
        graph = build_graph(llm, checkpointer, approve=approve)
        for update in graph.stream(
            initial_state,
            config={"configurable": {"thread_id": slug}},
            stream_mode="updates",
        ):
            node_name, node_output = next(iter(update.items()))
            _print_stage_summary(node_name, node_output)
            typer.echo(f"[{STAGE_LABELS[node_name]}] 단계를 종료합니다.")
            if stop_after is not None and node_name == stop_after.value:
                stopped_early = True
                break
            _maybe_print_next_stage_banner(node_name)

    _print_pipeline_footer(slug, stopped_early=stopped_early)


def _print_stage_summary(node_name: str, node_output: dict) -> None:
    if node_name == "interview":
        interview = node_output["interview"]
        typer.echo(f"  구체화된 설명: {interview.refined_brief}")
        if interview.assumptions:
            typer.echo("  가정:")
            for a in interview.assumptions:
                typer.echo(f"    - {a}")
        else:
            typer.echo("  가정: (없음 — 전부 응답함)")
    elif node_name == "analyze":
        components = node_output["components"]
        typer.echo(
            f"  통과 {len(components)}개 (걸러진 것 포함 전체 목록은 "
            "`scout show <slug> analyze`)"
        )
        for c in components:
            typer.echo(
                f"    [{c.necessity}] {c.name} ({c.kind}) — priority {c.priority}"
            )
            typer.echo(f"      이유: {c.necessity_reason}")
    elif node_name == "search":
        candidates = node_output["candidates"]
        typer.echo(
            f"  후보 {len(candidates)}개 (사실 원본은 `scout show <slug> search`)"
        )
        for c in candidates:
            fact_ids = ", ".join(f.id for f in c.dossier) or "(없음)"
            typer.echo(f"    {c.name} [{c.kind}] — {c.component}")
            typer.echo(f"      사실 {len(c.dossier)}개: {fact_ids}")
            for gap in c.dossier_gaps:
                typer.echo(f"      gap: {gap}")


def _maybe_print_next_stage_banner(node_name: str) -> None:
    idx = STAGE_ORDER.index(node_name)
    if idx + 1 >= len(STAGE_ORDER):
        return
    next_stage = STAGE_ORDER[idx + 1]
    if next_stage in IMPLEMENTED_STAGES:
        typer.echo(f"\n[{STAGE_LABELS[next_stage]}] 단계를 시작합니다.")


def _print_pipeline_footer(slug: str, *, stopped_early: bool) -> None:
    typer.echo(f"\n[OK] slug={slug}")
    if stopped_early:
        typer.echo(
            f"지정한 단계까지 실행을 마쳤습니다. `scout show {slug} <단계>`로 결과를 볼 수 있습니다."
        )
    else:
        typer.echo(
            f"다음 단계는 아직 구현되지 않았습니다. "
            f"`scout show {slug} <단계>`로 지금까지 결과를 볼 수 있습니다."
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
