"""interview 단계 — 되묻기로 막연한 요청을 구체화해 Interview를 만들고 runs에 저장한다.

LLM 1회 (000_기술스택-조사-에이전트-설계/stages/0-interview.md). 5개 질문은 코드가 CLI로
직접 묻는다 — LLM은 raw_description + 답변을 받아 refined_brief와 나머지 필드를 합성하는
역할 하나만 한다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import typer
from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from scout import store
from scout.prompts import INTERVIEW_PROMPT, INTERVIEW_RETRY_HINT
from scout.schemas import Interview

if TYPE_CHECKING:
    from langchain_aws import ChatBedrockConverse

    from scout.state import ScoutState

# (state 키, 질문, 미응답 시 기본값) — 순서가 되묻는 순서다. 001/stages/0-interview.md "질문 5개"
_QUESTIONS: list[tuple[str, str, str]] = [
    ("scale", "예상 사용자 규모는?", "미지정 (중소 규모 가정)"),
    ("budget", "월 인프라 예산은 얼마인가요? (숫자만, 모르면 Enter)", "미지정"),
    ("team", "팀 인원과 숙련 언어는?", "3인, 숙련 언어 미지정"),
    ("deadline", "데드라인은 몇 개월 후인가요?", "3개월"),
    (
        "data_sensitivity",
        "데이터 민감도는? (public / internal / regulated)",
        "internal",
    ),
]

Ask = Callable[[str, str], str]


class NonInteractive(Exception):
    """대화형 입력이 불가능한 환경(파이프·CI)에서 stdin이 즉시 EOF일 때."""


def _default_ask(question: str, default: str) -> str:
    try:
        return typer.prompt(
            f"? {question} [기본값: {default}]", default="", show_default=False
        )
    except (EOFError, typer.Abort):
        raise NonInteractive from None


def _collect_answers(ask: Ask) -> tuple[dict[str, str], list[str]]:
    """5개 질문을 순서대로 묻는다. 빈 입력·비대화형 모두 기본값 + assumptions 기록으로 처리한다."""
    answers: dict[str, str] = {}
    assumptions: list[str] = []
    for key, question, default in _QUESTIONS:
        try:
            response = ask(question, default).strip()
        except NonInteractive:
            for k, _q, d in _QUESTIONS:
                answers.setdefault(k, d)
            assumptions.append("비대화형 실행 — 전부 기본값 사용")
            break
        if response:
            answers[key] = response
        else:
            answers[key] = default
            assumptions.append(f"'{question}' 미응답 — 기본값 '{default}' 사용")
    return answers, assumptions


def _build_prompt_input(
    raw_description: str, answers: dict[str, str], default_notes: list[str]
) -> dict[str, str]:
    qa_lines = "\n".join(f"- {q}: {answers[key]}" for key, q, _d in _QUESTIONS)
    defaults_block = (
        "\n".join(f"- {n}" for n in default_notes)
        if default_notes
        else "(없음 — 전부 응답함)"
    )
    return {
        "raw_description": raw_description,
        "qa_lines": qa_lines,
        "defaults_block": defaults_block,
    }


def _recover_from_tool_call(raw: object) -> Interview | None:
    """budget_monthly_usd에 JSON null 대신 문자열 "null"을 쓰는 관찰된 버그를 보정해 재시도한다."""
    tool_calls = getattr(raw, "tool_calls", None)
    if not tool_calls:
        return None
    args = dict(tool_calls[0].get("args", {}))
    if isinstance(args.get("budget_monthly_usd"), str) and args[
        "budget_monthly_usd"
    ].strip().lower() in (
        "null",
        "none",
        "",
    ):
        args["budget_monthly_usd"] = None
    try:
        return Interview.model_validate(args)
    except ValidationError:
        return None


def run_interview(
    llm: ChatBedrockConverse,
    raw_description: str,
    *,
    ask: Ask = _default_ask,
) -> Interview:
    answers, default_notes = _collect_answers(ask)
    prompt_input = _build_prompt_input(raw_description, answers, default_notes)

    # prompt | llm — 스키마는 프롬프트 텍스트가 아니라 API에 tool로 전달된다
    structured_llm = llm.with_structured_output(Interview, include_raw=True)
    chain = INTERVIEW_PROMPT | structured_llm

    result = chain.invoke(prompt_input)
    interview = result["parsed"] or _recover_from_tool_call(result["raw"])
    if interview is None:
        retry_messages = [
            *INTERVIEW_PROMPT.invoke(prompt_input).to_messages(),
            HumanMessage(INTERVIEW_RETRY_HINT),
        ]
        result = structured_llm.invoke(retry_messages)
        interview = result["parsed"] or _recover_from_tool_call(result["raw"])
    if interview is None:
        raise RuntimeError(f"Interview 구조화 출력 파싱 실패: {result['raw']}")

    # 코드 쪽 안전망 — judge가 assumptions를 놓쳐도 기본값 사용 사실 자체는 항상 남는다.
    merged_assumptions = list(dict.fromkeys([*interview.assumptions, *default_notes]))
    return interview.model_copy(
        update={"raw_description": raw_description, "assumptions": merged_assumptions}
    )


def interview_node(state: ScoutState, *, llm: ChatBedrockConverse) -> dict:
    interview = run_interview(llm, state["description"])
    store.upsert_run(
        state["slug"],
        state["description"],
        datetime.now(UTC).isoformat(),
        interview,
    )
    return {"interview": interview}
