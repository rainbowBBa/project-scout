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
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError

from scout import store
from scout.agentkit import build_transcript, collect_tool_calls
from scout.approval import SearchGate, default_approve, wrap_web_search
from scout.llm import invoke_structured
from scout.mcp_client import make_mcp_client
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
    from scout.schemas import Component, Interview
    from scout.state import ScoutState

# LangGraph의 recursion_limit은 **툴 호출 수가 아니라 superstep 수**다. ReAct는 한 바퀴가
# model + tools 두 스텝이라 10이면 툴 호출 4~5회쯤이다. 프로토타입에서는 그 정도로 충분하다 —
# 설계는 후보 이름·어휘만 확인하면 되고, 루프를 오래 돌면 누적 입력이 토큰을 그대로 먹는다.
_RECURSION_LIMIT = 10
# 설계는 요소별로 펼치지 않고 한 번 돌므로 예산이 실행 전체 기준이다
# (`search`는 결정 지점당 5회).
_WEB_SEARCH_BUDGET = 3

_PASSING_NECESSITY = {"essential", "valuable"}


def _prompt_input(interview: Interview) -> dict[str, str]:
    return {
        "refined_brief": interview.refined_brief,
        "assumptions": "\n".join(f"- {a}" for a in interview.assumptions) or "(없음)",
    }


async def explore(agent, task: str) -> tuple[list, bool]:
    """툴 루프를 돌리고 (메시지, 한도에 걸렸는지)를 돌려준다.

    `ainvoke`가 아니라 `astream`을 쓰는 이유는 **한도 초과가 예외이기 때문**이다 —
    `GraphRecursionError`는 상태를 담아주지 않아서 `ainvoke`로 받으면 그때까지 모은
    툴 기록이 함께 날아간다. 한도를 낮춘 만큼 걸릴 일이 실제로 생기고, 그때 부분
    기록만으로도 설계를 뽑는 게 아무것도 없이 죽는 것보다 낫다 (불변식 11).
    """
    messages: list = []
    try:
        # recursion_limit을 반드시 넘긴다 — create_agent는 그래프에 9999를 바인딩해둔다.
        async for state in agent.astream(
            {"messages": [HumanMessage(task)]},
            config={"recursion_limit": _RECURSION_LIMIT},
            stream_mode="values",
        ):
            messages = state["messages"]
    except GraphRecursionError:
        return messages, True
    return messages, False


async def run_design(
    llm: ChatBedrockConverse,
    interview: Interview,
    tools: dict[str, BaseTool],
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
    messages, truncated = await explore(
        agent, DESIGN_AGENT_TASK_PROMPT.format(**prompt_input)
    )

    design, raw = invoke_structured(
        DESIGN_EXTRACT_PROMPT,
        llm.with_structured_output(Design, include_raw=True),
        {
            **prompt_input,
            "transcript": build_transcript(collect_tool_calls(messages), messages),
        },
        DESIGN_EXTRACT_RETRY_HINT,
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
    interview: Interview, llm: ChatBedrockConverse, gate: SearchGate
) -> tuple[Design, bool]:
    tools = {t.name: t for t in await make_mcp_client().get_tools()}
    if "web_search" in tools:
        tools = {
            **tools,
            "web_search": wrap_web_search(
                tools["web_search"], gate, budget=_WEB_SEARCH_BUDGET
            ),
        }
    return await run_design(llm, interview, tools)


def design_node(
    state: ScoutState,
    *,
    llm: ChatBedrockConverse,
    approve: Approve = default_approve,
) -> dict:
    slug = state["slug"]
    # 게이트는 이 노드에서 새로 만든다 — search_node와 공유하면 SearchGate._lock이
    # 다른 이벤트 루프에 묶인다 (두 노드가 각각 asyncio.run으로 루프를 연다).
    gate = SearchGate(approve=approve)
    design, truncated = asyncio.run(_run(state["interview"], llm, gate))

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
            f"툴 탐색이 한도({_RECURSION_LIMIT} superstep)에 걸려 중단됨 — "
            "여기까지 모은 기록으로 설계를 뽑았다",
        )
    for note in gate.notes:
        store.add_gap(slug, "design", note)

    return {"architecture": design.architecture, "components": selected}
