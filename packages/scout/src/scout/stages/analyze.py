"""analyze 단계 — interview의 refined_brief에서 개발에 필요한 요소를 도출하고
necessity·priority를 매겨 components에 저장한다.

LLM 1회 (001/stages/1-analyze.md). 걸러진 것까지 전부 저장하되, 다음 단계로는
necessity가 essential/valuable인 것 중 priority 상위 max_components개만 넘긴다
("도출과 통과를 분리한다").
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scout import store
from scout.llm import invoke_structured
from scout.prompts import ANALYZE_PROMPT, ANALYZE_RETRY_HINT
from scout.schemas import Analysis, Component

if TYPE_CHECKING:
    from langchain_aws import ChatBedrockConverse

    from scout.schemas import Interview
    from scout.state import ScoutState

_PASSING_NECESSITY = {"essential", "valuable"}


def _build_prompt_input(interview: Interview) -> dict[str, str]:
    return {
        "refined_brief": interview.refined_brief,
        "assumptions": "\n".join(f"- {a}" for a in interview.assumptions) or "(없음)",
    }


def run_analyze(llm: ChatBedrockConverse, interview: Interview) -> Analysis:
    prompt_input = _build_prompt_input(interview)

    structured_llm = llm.with_structured_output(Analysis, include_raw=True)
    analysis, raw = invoke_structured(
        ANALYZE_PROMPT, structured_llm, prompt_input, ANALYZE_RETRY_HINT
    )
    if analysis is None:
        raise RuntimeError(f"Analysis 구조화 출력 파싱 실패: {raw}")
    return analysis


def select_passing_components(
    components: list[Component], max_components: int
) -> list[Component]:
    """search로 넘길 상위 요소만 고른다 — necessity가 essential/valuable이고 priority가
    낮은(=중요한) 순. 걸러진 것도 components 테이블에는 전부 남는다 — 여기서 자르는 건
    상태로 넘기는 부분집합일 뿐이다.
    """
    passing = [c for c in components if c.necessity in _PASSING_NECESSITY]
    return sorted(passing, key=lambda c: c.priority)[:max_components]


def analyze_node(state: ScoutState, *, llm: ChatBedrockConverse) -> dict:
    analysis = run_analyze(llm, state["interview"])

    store.upsert_components(state["slug"], analysis.components)
    if not analysis.components:
        store.add_gap(
            state["slug"], "analyze", "요소가 도출되지 않음 — 설명이 너무 짧거나 모호함"
        )

    selected = select_passing_components(
        analysis.components, state.get("max_components", 3)
    )
    return {"components": selected}
