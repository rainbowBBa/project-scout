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
from langchain_core.globals import set_llm_cache
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import ValidationError

from scout import store
from scout.approval import auto_approve, default_approve
from scout.config import Settings
from scout.graph import build_graph, make_slug
from scout.llm import make_llm
from scout.llm_cache import SqliteLLMCache
from scout.mcp_client import make_mcp_client

app = typer.Typer()

# 파이프라인 6단계 전체 이름. 아직 구현된 노드만 IMPLEMENTED_STAGES에 있다 — STEP이 끝날 때마다 하나씩 늘어난다.
STAGE_ORDER = ["interview", "design", "search", "verify", "evaluate", "report"]
IMPLEMENTED_STAGES = ["interview", "design", "search", "verify", "evaluate", "report"]
STAGE_LABELS = {
    "interview": "인터뷰",
    "design": "설계",
    "search": "검색",
    "verify": "검증",
    "evaluate": "평가",
    "report": "리포트",
}


class ShowStage(str, Enum):
    interview = "interview"
    design = "design"
    search = "search"
    verify = "verify"
    evaluate = "evaluate"


class Stage(str, Enum):
    interview = "interview"
    design = "design"
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

    # 개발용 LLM 응답 캐시. 기본 off — 켜진 채 실전 실행이 돌면 어제의 판정이
    # 오늘의 추천으로 나온다. doctor에는 걸지 않는다 (실측이 목적인 명령이다).
    cache = None
    if settings.scout_llm_cache:
        cache = SqliteLLMCache(settings.scout_llm_cache_path)
        set_llm_cache(cache)
        typer.echo(f"[개발] LLM 캐시 사용: {settings.scout_llm_cache_path}")

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
    report_path: str | None = None
    approve = auto_approve if auto_approve_search else default_approve
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
            if node_name == "report":
                report_path = node_output["report_path"]
            if stop_after is not None and node_name == stop_after.value:
                stopped_early = True
                break
            _maybe_print_next_stage_banner(node_name)

    _print_pipeline_footer(
        slug, stopped_early=stopped_early, report_path=report_path, cache=cache
    )


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
    elif node_name == "design":
        architecture = node_output["architecture"]
        components = node_output["components"]
        typer.echo(f"  설계: {architecture.summary}")
        if architecture.build_order:
            typer.echo(f"  무엇부터: {' → '.join(architecture.build_order)}")
        typer.echo(
            f"  통과 {len(components)}개 (닫힌 결정·걸러진 것 포함 전체 목록은 "
            "`scout show <slug> design`)"
        )
        for c in components:
            typer.echo(
                f"    [{c.necessity}] {c.name} ({c.kind}) — priority {c.priority}"
            )
            typer.echo(f"      정할 것: {c.decision_question}")
            typer.echo(f"      힌트: {', '.join(c.search_hints) or '(없음)'}")
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
    elif node_name == "verify":
        verdicts = node_output["verdicts"]
        solved = sum(1 for v in verdicts if v.solves_it)
        typer.echo(
            f"  판정 {len(verdicts)}개 — 해결 {solved} / 미해결 {len(verdicts) - solved} "
            "(전문은 `scout show <slug> verify`)"
        )
        for v in verdicts:
            mark = "O" if v.solves_it else "X"
            typer.echo(
                f"    [{mark}] {v.candidate} — confidence {v.confidence} "
                f"(인용 {len(v.citations)}건)"
            )
            typer.echo(f"      이유: {v.solves_reason}")
            for claim in v.unsupported_claims:
                typer.echo(f"      근거없음: {claim}")
    elif node_name == "evaluate":
        picks = node_output["element_picks"]
        typer.echo(
            f"  요소 {len(picks)}개 순위 산정 "
            "(점수 전문은 `scout show <slug> evaluate`)"
        )
        for pick in picks:
            typer.echo(f"    [{pick.component}] 1위 {pick.winner} ({pick.margin})")
            typer.echo(f"      선정 이유: {pick.winner_reason}")
            typer.echo(f"      순위: {' > '.join(pick.ranking)}")
            for score in pick.scores:
                typer.echo(
                    f"        {score.candidate} overall {score.overall} — {score.score_reason}"
                )
            typer.echo(f"      2위 참고: {pick.runner_up_note}")
        final = node_output.get("final_design")
        if final is None:
            typer.echo("  확정 설계: 없음 (`scout show <slug> evaluate`의 gaps 참고)")
        else:
            typer.echo(f"\n  확정 설계: {final.summary}")
            typer.echo(f"    구조: {final.shape}")
            if final.changes_from_design:
                typer.echo("    설계가 바뀐 곳:")
                for change in final.changes_from_design:
                    typer.echo(f"      - {change}")
            else:
                # 빈 것도 정보다 — 기본틀이 조사를 견뎠다 (불변식 12)
                typer.echo(
                    "    설계가 바뀐 곳: 없음 — 조사 결과가 기본틀을 바꾸지 않았다"
                )
            if final.unresolved:
                typer.echo(f"    미해결 {len(final.unresolved)}건")
    elif node_name == "report":
        summary = node_output["report_summary"]
        for row in summary["stack"]:
            margin_note = "  (근접)" if row["margin"] == "close" else ""
            overall = "-" if row["overall"] is None else str(row["overall"])
            typer.echo(
                f"  {row['component']:<18} {row['candidate']:<20} {overall}{margin_note}"
            )
        typer.echo(
            f"\n  걸러낸 요소 {summary['filtered_count']}개 · "
            f"탈락 후보 {summary['rejected_count']}개 · "
            f"grounding 위반 {summary['grounding_violations_total']}건"
        )


def _maybe_print_next_stage_banner(node_name: str) -> None:
    idx = STAGE_ORDER.index(node_name)
    if idx + 1 >= len(STAGE_ORDER):
        return
    next_stage = STAGE_ORDER[idx + 1]
    if next_stage in IMPLEMENTED_STAGES:
        typer.echo(f"\n[{STAGE_LABELS[next_stage]}] 단계를 시작합니다.")


def _print_pipeline_footer(
    slug: str, *, stopped_early: bool, report_path: str | None
) -> None:
    typer.echo(f"\n[OK] slug={slug}")
    if report_path is not None:
        typer.echo(f"리포트: {report_path}")
    elif stopped_early:
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
    elif stage is ShowStage.design:
        architecture = store.get_design(slug)
        result = {
            "architecture": architecture.model_dump() if architecture else None,
            "components": [c.model_dump() for c in store.get_components(slug)],
        }
    elif stage is ShowStage.search:
        result = {
            "candidates": [c.model_dump() for c in store.get_candidates(slug)],
        }
    elif stage is ShowStage.verify:
        result = [v.model_dump() for v in store.get_verdicts(slug)]
    else:  # evaluate
        final = store.get_final_design(slug)
        result = {
            "scores": store.get_scores(slug),
            "picks": store.get_picks(slug),
            "final_design": final.model_dump() if final else None,
        }

    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
