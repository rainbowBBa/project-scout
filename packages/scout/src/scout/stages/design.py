"""design 단계 — 구현 설계를 세우고 비교가 필요한 결정 지점을 뽑는다 (001/stages/1-design.md).

`search`와 같은 2-pass다: 에이전트가 툴로 탐색하고, 코드가 접은 기록에서 `Design`을
구조화 출력으로 뽑는다.

★ 이 단계의 툴 결과는 `facts`에 들어가지 않는다 (불변식 15) — `store.upsert_facts`를
부르지 않는다. `test_design_no_facts`가 검사한다.

걸러진 것까지 전부 저장하되 다음 단계로는 통과 필터 셋을 지난 것만 넘긴다.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from langchain.agents import create_agent

from scout import store
from scout.agentkit import (
    DEFAULT_TOOL_PAYLOAD_CHARS,
    build_transcript,
    collect_tool_calls,
    run_agent_loop,
)
from scout.approval import SearchGate, default_approve, wrap_web_search
from scout.llm import invoke_structured
from scout.mcp_client import make_mcp_client
from scout.progress import step, wrap_all
from scout.prompts import (
    DESIGN_AGENT_SYSTEM_PROMPT,
    DESIGN_AGENT_TASK_PROMPT,
    DESIGN_EXTRACT_PROMPT,
    DESIGN_EXTRACT_RETRY_HINT,
)
from scout.schemas import Design

if TYPE_CHECKING:
    from langchain_aws import ChatBedrockConverse
    from langchain_core.tools import BaseTool

    from scout.approval import Approve
    from scout.config import Settings
    from scout.schemas import Component, Interview
    from scout.state import ScoutState

_PASSING_NECESSITY = {"essential", "valuable"}
DEFAULT_MIN_ALTERNATIVES = 2


def _prompt_input(interview: Interview) -> dict[str, str]:
    return {
        "refined_brief": interview.refined_brief,
        "assumptions": "\n".join(f"- {a}" for a in interview.assumptions) or "(없음)",
    }


async def run_design(
    llm: ChatBedrockConverse,
    interview: Interview,
    tools: dict[str, BaseTool],
    recursion_limit: int,
    *,
    web_search_budget: int,
    payload_chars: int = DEFAULT_TOOL_PAYLOAD_CHARS,
) -> tuple[Design, bool]:
    # checkpointer=False — 안 주면 바깥 그래프의 SqliteSaver(동기 전용)를 물려받는데
    # 이 에이전트는 astream으로 돈다
    agent = create_agent(
        llm,
        list(tools.values()),
        # 예산을 주입한다 — 굳혀두면 설정을 내렸을 때 프롬프트가 거짓이 된다
        system_prompt=DESIGN_AGENT_SYSTEM_PROMPT.format(
            web_search_budget=web_search_budget
        ),
        checkpointer=False,
    )
    prompt_input = _prompt_input(interview)
    step(f"설계 탐색 시작 — 툴 최대 {recursion_limit} superstep")
    messages, truncated = await run_agent_loop(
        agent, DESIGN_AGENT_TASK_PROMPT.format(**prompt_input), recursion_limit
    )
    if truncated:
        step("툴 탐색 한도 도달 — 여기까지 모은 기록으로 설계를 뽑는다")
    step("설계 추출")

    design, raw = invoke_structured(
        DESIGN_EXTRACT_PROMPT,
        llm.with_structured_output(Design, include_raw=True),
        {
            **prompt_input,
            "transcript": build_transcript(
                collect_tool_calls(messages), messages, payload_chars=payload_chars
            ),
        },
        DESIGN_EXTRACT_RETRY_HINT,
        schema=Design,
    )
    if design is None:
        raise RuntimeError(f"Design 구조화 출력 파싱 실패: {raw}")
    return design, truncated


def close_undecidable(
    components: list[Component], *, min_alternatives: int = DEFAULT_MIN_ALTERNATIVES
) -> list[Component]:
    """고를 보기가 없는 결정 지점을 코드가 닫힌 결정으로 내린다 (불변식 18).

    프롬프트 반례로는 못 막아서 코드가 내린다. `no_comparison_reason`을 채우므로
    보고서에 이유가 남는다 (불변식 12). 반환값은 내려진 것들 — 호출자가 `gaps`에 남긴다.
    """
    closed: list[Component] = []
    for c in components:
        if not c.needs_comparison or len(c.alternatives) >= min_alternatives:
            continue
        only = c.alternatives[0] if c.alternatives else ""
        c.needs_comparison = False
        c.no_comparison_reason = (
            f"설계에서 이미 정해졌다 — {only}뿐이라 비교할 대안이 없다"
            if only
            else "고를 보기가 제시되지 않았다 — 비교할 선택이 아니라 설계 판단이다"
        )
        closed.append(c)
    return closed


def select_passing_components(
    components: list[Component],
    max_components: int,
    *,
    min_alternatives: int = DEFAULT_MIN_ALTERNATIVES,
) -> list[Component]:
    """search로 넘길 상위 결정 지점만 고른다 — 필터가 셋이다.

    `necessity` · `needs_comparison` · `alternatives` 개수. priority가 낮은(=중요한) 순.
    걸러진 것도 `components` 테이블에는 전부 남는다 — 여기서 자르는 건 상태로 넘기는
    부분집합이다.

    셋째 축은 `close_undecidable`과 중복이지만, 저장된 결정 지점을 다시 읽을 때
    마지막 방어가 된다.
    """
    passing = [
        c
        for c in components
        if c.necessity in _PASSING_NECESSITY
        and c.needs_comparison
        and len(c.alternatives) >= min_alternatives
    ]
    return sorted(passing, key=lambda c: c.priority)[:max_components]


def _record_gaps(
    slug: str,
    design: Design,
    selected: list[Component],
    closed: list[Component],
) -> None:
    if not design.components:
        store.add_gap(
            slug, "design", "결정 지점이 도출되지 않음 — 설명이 너무 짧거나 모호함"
        )
    if design.components and all(c.needs_comparison for c in design.components):
        store.add_gap(
            slug,
            "design",
            "needs_comparison이 전부 true — 프롬프트 반례가 안 먹혔을 수 있다",
        )
    if design.components and all(
        c.necessity in _PASSING_NECESSITY for c in design.components
    ):
        store.add_gap(
            slug, "design", "necessity가 전부 essential/valuable — 걸러낸 것이 없다"
        )
    for component in closed:
        store.add_gap(
            slug,
            "design",
            f"'{component.name}': {component.no_comparison_reason} "
            f"(정할 것: {component.decision_question})",
        )
    # 힌트가 비면 search가 한국어 추상어로 검색한다 (불변식 16). 파이프라인은
    # 그래도 돌기 때문에 기록으로 남긴다
    for component in selected:
        if not component.search_hints:
            store.add_gap(
                slug,
                "design",
                f"'{component.name}': search_hints가 비어 조사가 얕아진다",
            )


async def _run(
    interview: Interview,
    llm: ChatBedrockConverse,
    gate: SearchGate,
    settings: Settings,
) -> tuple[Design, bool]:
    client = make_mcp_client(settings.scout_mcp_read_timeout_seconds)
    tools = {t.name: t for t in await client.get_tools()}
    # 진행 표시가 안쪽, 승인 게이트가 바깥쪽 — 거부된 검색의 진행 줄은 찍히지 않는다
    tools = wrap_all(tools)
    if "web_search" in tools:
        tools = {
            **tools,
            "web_search": wrap_web_search(
                tools["web_search"], gate, budget=settings.scout_design_web_searches
            ),
        }
    return await run_design(
        llm,
        interview,
        tools,
        settings.scout_design_recursion_limit,
        web_search_budget=settings.scout_design_web_searches,
        payload_chars=settings.scout_tool_payload_chars,
    )


def design_node(
    state: ScoutState,
    *,
    llm: ChatBedrockConverse,
    approve: Approve = default_approve,
) -> dict:
    from scout.config import Settings

    slug = state["slug"]
    settings = Settings()
    # 게이트는 노드마다 새로 만든다 — 공유하면 _lock이 다른 이벤트 루프에 묶인다
    gate = SearchGate(
        approve=approve, max_rejections=settings.scout_max_search_rejections
    )
    design, truncated = asyncio.run(_run(state["interview"], llm, gate, settings))

    # 쓰기 전에 이전 실행의 산출물을 비운다
    store.clear_stage_output(slug, "design")
    store.upsert_design(slug, design.architecture)
    # 저장 전에 내린다 — DB에 내려간 상태가 들어가야 report가 이유를 렌더링한다
    closed = close_undecidable(
        design.components, min_alternatives=settings.scout_min_alternatives
    )
    store.upsert_components(slug, design.components)

    selected = select_passing_components(
        design.components,
        state.get("max_components", settings.scout_max_components),
        min_alternatives=settings.scout_min_alternatives,
    )
    _record_gaps(slug, design, selected, closed)
    if truncated:
        store.add_gap(
            slug,
            "design",
            f"툴 탐색이 한도({settings.scout_design_recursion_limit} superstep)에 "
            "걸려 중단됨 — "
            "여기까지 모은 기록으로 설계를 뽑았다",
        )
    for note in gate.notes:
        store.add_gap(slug, "design", note)

    return {"architecture": design.architecture, "components": selected}
