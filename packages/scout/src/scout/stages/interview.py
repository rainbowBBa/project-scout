"""interview 단계 — 대화형으로 되물어 막연한 요청을 구체화해 Interview를 만들고
runs에 저장한다.

질문 개수·내용은 코드가 정하지 않는다. LLM이 매 턴 "질문 하나 더" 또는 "충분함"을
판단한다 (000_기술스택-조사-에이전트-설계/stages/0-interview.md). 이 대화 루프는
파이썬 for-loop가 아니라 작은 LangGraph 서브그래프로 짠다 — 순환은 조건 엣지로
표현한다:

    START → ask_question ─(질문 있음)→ get_answer ─(계속)→ ask_question (반복)
                │                                     │
          (done/한도 도달)                      (비대화형 입력)
                └──────────────→ synthesize ←─────────┘
                                      │
                                     END

외부 파이프라인(scout/graph.py)에서 보이는 "interview" 노드는 하나 그대로다 —
그 노드가 내부적으로 이 서브그래프를 돈다.
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, TypedDict

import typer
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from scout import store
from scout.llm import invoke_structured
from scout.progress import while_asking
from scout.prompts import (
    INTERVIEW_SYNTHESIS_PROMPT,
    INTERVIEW_SYNTHESIS_RETRY_HINT,
    INTERVIEW_TURN_PROMPT,
    INTERVIEW_TURN_RETRY_HINT,
)
from scout.schemas import Interview, InterviewTurn

if TYPE_CHECKING:
    from langchain_aws import ChatBedrockConverse

    from scout.state import ScoutState

Ask = Callable[[str], str]

_DEFAULT_MAX_TURNS = 5


class NonInteractive(Exception):
    """대화형 입력이 불가능한 환경(파이프·CI)에서 stdin이 즉시 EOF일 때."""


def _default_ask(question: str) -> str:
    # stdin을 읽는 함수는 `while_asking()` 안에서 읽는다 (001/09-출력양식.md).
    # `interview`는 병렬이 아니라 지금은 보류할 줄이 없지만, 규칙을 한 군데만 지키면
    # 다음 사람이 "왜 여기만?"에서 판단을 다시 하게 된다.
    with while_asking():
        try:
            # 열 2의 `? ` — 화자를 밝히지 않는다. `?`가 "당신이 답할 차례"를 말하고
            # 들여쓰기가 [인터뷰] 소속을 말한다 (001/09-출력양식.md).
            return typer.prompt(f"  ? {question}", default="", show_default=False)
        except EOFError, typer.Abort:
            raise NonInteractive from None


class _InterviewState(TypedDict, total=False):
    history: Annotated[list[BaseMessage], operator.add]
    gap_notes: Annotated[list[str], operator.add]
    turn_count: int
    max_turns: int
    pending_question: str | None
    stop: bool
    interview: Interview | None


def _decide_next_turn(
    llm: ChatBedrockConverse, history: list[BaseMessage]
) -> InterviewTurn | None:
    """다음 질문 또는 종료 여부를 판단한다. 재시도까지 실패하면 None — 호출부가 종료로 처리한다."""
    structured_llm = llm.with_structured_output(InterviewTurn, include_raw=True)
    turn, _raw = invoke_structured(
        INTERVIEW_TURN_PROMPT,
        structured_llm,
        {"history": history},
        INTERVIEW_TURN_RETRY_HINT,
        schema=InterviewTurn,
    )
    return turn


def _synthesize_interview(
    llm: ChatBedrockConverse, history: list[BaseMessage], gap_notes: list[str]
) -> Interview:
    gap_block = (
        "\n".join(f"- {n}" for n in gap_notes) if gap_notes else "(없음 — 전부 응답함)"
    )
    prompt_input = {"history": history, "gap_notes": gap_block}

    structured_llm = llm.with_structured_output(Interview, include_raw=True)
    interview, raw = invoke_structured(
        INTERVIEW_SYNTHESIS_PROMPT,
        structured_llm,
        prompt_input,
        INTERVIEW_SYNTHESIS_RETRY_HINT,
        schema=Interview,
    )
    if interview is None:
        raise RuntimeError(f"Interview 구조화 출력 파싱 실패: {raw}")

    # 코드 쪽 안전망 — judge가 gap_notes를 놓쳐도 미응답 사실 자체는 항상 남는다.
    merged_assumptions = list(dict.fromkeys([*interview.assumptions, *gap_notes]))
    return interview.model_copy(update={"assumptions": merged_assumptions})


def _ask_question_node(state: _InterviewState, *, llm: ChatBedrockConverse) -> dict:
    if state["turn_count"] >= state["max_turns"]:
        return {
            "pending_question": None,
            "gap_notes": [
                f"질문 {state['max_turns']}회 한도 도달 — 남은 판단은 추정으로 채움"
            ],
        }

    turn = _decide_next_turn(llm, state["history"])
    if turn is None or turn.done or not turn.question:
        return {"pending_question": None}
    return {
        "history": [AIMessage(turn.question)],
        "turn_count": state["turn_count"] + 1,
        "pending_question": turn.question,
    }


def _route_after_ask(state: _InterviewState) -> str:
    return "get_answer" if state.get("pending_question") else "synthesize"


def _get_answer_node(state: _InterviewState, *, ask: Ask) -> dict:
    question = state["pending_question"]
    assert question is not None
    try:
        answer = ask(question).strip()
    except NonInteractive:
        return {
            "gap_notes": ["비대화형 실행 — 남은 질문 생략, 알고 있는 정보로 판단"],
            "stop": True,
        }
    if answer:
        return {"history": [HumanMessage(answer)]}
    return {
        "history": [HumanMessage("(답변 없음 — 알아서 합리적으로 가정해라)")],
        "gap_notes": [f"'{question}' 미응답"],
    }


def _route_after_answer(state: _InterviewState) -> str:
    return "synthesize" if state.get("stop") else "ask_question"


def _synthesize_node(state: _InterviewState, *, llm: ChatBedrockConverse) -> dict:
    interview = _synthesize_interview(llm, state["history"], state["gap_notes"])
    return {"interview": interview}


def _build_interview_graph(llm: ChatBedrockConverse, ask: Ask):
    graph = StateGraph(_InterviewState)
    graph.add_node("ask_question", lambda state: _ask_question_node(state, llm=llm))
    graph.add_node("get_answer", lambda state: _get_answer_node(state, ask=ask))
    graph.add_node("synthesize", lambda state: _synthesize_node(state, llm=llm))
    graph.add_edge(START, "ask_question")
    graph.add_conditional_edges(
        "ask_question",
        _route_after_ask,
        {"get_answer": "get_answer", "synthesize": "synthesize"},
    )
    graph.add_conditional_edges(
        "get_answer",
        _route_after_answer,
        {"ask_question": "ask_question", "synthesize": "synthesize"},
    )
    graph.add_edge("synthesize", END)
    return graph.compile()  # 체크포인터 불필요 — 한 번의 동기 호출 안에서 끝난다


def run_interview(
    llm: ChatBedrockConverse,
    raw_description: str,
    *,
    ask: Ask = _default_ask,
    max_turns: int = _DEFAULT_MAX_TURNS,
) -> Interview:
    result = _build_interview_graph(llm, ask).invoke(
        {
            "history": [HumanMessage(raw_description)],
            "gap_notes": [],
            "turn_count": 0,
            "max_turns": max_turns,
            "pending_question": None,
            "stop": False,
        }
    )
    interview = result["interview"]
    return interview.model_copy(update={"raw_description": raw_description})


def interview_node(state: ScoutState, *, llm: ChatBedrockConverse) -> dict:
    interview = run_interview(
        llm, state["description"], max_turns=state.get("max_turns", _DEFAULT_MAX_TURNS)
    )
    store.upsert_run(
        state["slug"],
        state["description"],
        datetime.now(UTC).isoformat(),
        interview,
    )
    return {"interview": interview}
