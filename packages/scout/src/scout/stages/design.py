"""design 단계 — 구현 설계를 세우고 비교가 필요한 결정 지점을 뽑는다.

`search`와 같은 2-pass다 (001/stages/1-design.md):
1. ReAct 에이전트가 툴을 부르며 설계를 세운다 — 후보 이름·패턴명·생태계 어휘를 확인
2. 코드가 접은 기록(`build_transcript`)에서 `Design`을 구조화 출력으로 뽑는다

★ **이 단계의 툴 결과는 `facts`에 들어가지 않는다** (불변식 15). dossier는 `search`만
만든다. 설계 중에 스쳐본 값을 섞으면 kind 라우팅·top-up을 거치지 않은 사실이 judge의
인용 대상이 되어, grounding은 통과하는데 후보마다 근거 커버리지가 달라진다.
그래서 여기서는 `store.upsert_facts`를 부르지 않는다 — `test_design_no_facts`가 검사한다.

걸러진 것까지 전부 저장하되, 다음 단계로는 **비교가 필요하고**(`needs_comparison`)
`necessity`가 essential/valuable인 것 중 priority 상위 max_components개만 넘긴다
("도출과 통과를 분리한다").
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from langchain.agents import create_agent

from scout import store
from scout.agentkit import build_transcript, collect_tool_calls, run_agent_loop
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
) -> tuple[Design, bool]:
    # checkpointer=False — 안 주면 바깥 그래프의 SqliteSaver(동기 전용)를 물려받는데
    # 이 에이전트는 astream으로 돈다 ("SqliteSaver does not support async methods").
    agent = create_agent(
        llm,
        list(tools.values()),
        system_prompt=DESIGN_AGENT_SYSTEM_PROMPT,
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
            "transcript": build_transcript(collect_tool_calls(messages), messages),
        },
        DESIGN_EXTRACT_RETRY_HINT,
        schema=Design,
    )
    if design is None:
        raise RuntimeError(f"Design 구조화 출력 파싱 실패: {raw}")
    return design, truncated


def select_passing_components(
    components: list[Component], max_components: int
) -> list[Component]:
    """search로 넘길 상위 결정 지점만 고른다 — 필터가 둘이다.

    `necessity`가 essential/valuable이고 **비교가 필요한** 것 중 priority가 낮은
    (=중요한) 순. 걸러진 것도 components 테이블에는 전부 남는다 — 여기서 자르는 건
    상태로 넘기는 부분집합일 뿐이다.
    """
    passing = [
        c
        for c in components
        if c.necessity in _PASSING_NECESSITY and c.needs_comparison
    ]
    return sorted(passing, key=lambda c: c.priority)[:max_components]


def _record_gaps(slug: str, design: Design, selected: list[Component]) -> None:
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
    # 힌트가 비면 search가 한국어 추상어로 npm_search를 부르게 된다 (불변식 16).
    # 파이프라인은 그래도 돌기 때문에 조용히 회귀하지 않도록 기록으로 남긴다.
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
    tools = {t.name: t for t in await make_mcp_client().get_tools()}
    # 진행 표시가 안쪽, 승인 게이트가 바깥쪽 — 거부된 검색의 진행 줄은 찍히지 않는다
    # (001/09-출력양식.md).
    tools = wrap_all(tools)
    if "web_search" in tools:
        tools = {
            **tools,
            "web_search": wrap_web_search(
                tools["web_search"], gate, budget=settings.scout_design_web_searches
            ),
        }
    return await run_design(
        llm, interview, tools, settings.scout_design_recursion_limit
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
    # 게이트는 이 노드에서 새로 만든다 — search_node와 공유하면 SearchGate._lock이
    # 다른 이벤트 루프에 묶인다 (두 노드가 각각 asyncio.run으로 루프를 연다).
    gate = SearchGate(approve=approve)
    design, truncated = asyncio.run(_run(state["interview"], llm, gate, settings))

    # 쓰기 전에 이전 실행의 산출물을 비운다 (store.clear_stage_output 참고)
    store.clear_stage_output(slug, "design")
    store.upsert_design(slug, design.architecture)
    store.upsert_components(slug, design.components)

    selected = select_passing_components(
        design.components, state.get("max_components", 3)
    )
    _record_gaps(slug, design, selected)
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
