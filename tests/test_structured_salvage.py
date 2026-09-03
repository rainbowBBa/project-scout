"""구조화 출력 파싱 구제(`llm._salvage`)를 검사한다 — LLM도 네트워크도 쓰지 않는다.

설계 주장을 검증하는 6종과 성격이 다르다(07-검증.md 표에는 없다). 그래도 테스트가
필요한 이유는 **이 경로가 없으면 파이프라인이 멈추는 것을 실측했기** 때문이다 —
모델이 `Design` 한 객체를 `architecture` / `components` 두 `tool_use` 블록으로 쪼개
보내고, `with_structured_output`의 파서는 `first_tool_only=True`라 첫 블록만 본다.
조용히 되돌아가면 E2E가 다시 죽는다.
"""

from langchain_core.messages import AIMessage
from scout.llm import _salvage
from scout.schemas import Design

_ARCH = {
    "summary": "단일 Node 백엔드",
    "shape": "브라우저 → Node → PG",
    "data_flow": "전송 → 기록 → 브로드캐스트",
    "build_order": ["스키마"],
    "open_questions": [],
}
_COMPONENT = {
    "name": "실시간 메시지 전달",
    "kind": "feature",
    "role_in_design": "양방향 연결 유지",
    "decision_question": "전달 계층은 무엇인가",
    "constraints": ["Node 지원"],
    "needs_comparison": True,
    "no_comparison_reason": "",
    "necessity": "essential",
    "necessity_reason": "200명 핵심",
    "priority": 1,
    "approach_notes": "",
    "search_hints": ["socket.io", "ws websocket library node"],
}


def _result(parsed, *arg_blocks):
    calls = [
        {"name": "Design", "args": a, "id": str(i), "type": "tool_call"}
        for i, a in enumerate(arg_blocks)
    ]
    return {
        "parsed": parsed,
        "parsing_error": None if parsed else "boom",
        "raw": AIMessage(content="", tool_calls=calls),
    }


def test_already_parsed_passes_through():
    assert _salvage(_result("그대로"), Design) == "그대로"


def test_merges_one_object_split_across_blocks():
    """★ 실측된 실패 모드 — 각 블록은 필드 누락으로 실패하지만 합치면 완전하다."""
    got = _salvage(
        _result(None, {"architecture": _ARCH}, {"components": [_COMPONENT]}), Design
    )

    assert got is not None, "블록을 합치지 않으면 파이프라인이 여기서 멈춘다"
    assert got.architecture.shape == "브라우저 → Node → PG"
    assert got.components[0].search_hints == ["socket.io", "ws websocket library node"]


def test_takes_a_single_valid_block():
    complete = {"architecture": _ARCH, "components": [_COMPONENT]}

    got = _salvage(_result(None, complete), Design)

    assert got is not None and len(got.components) == 1


def test_recovers_when_only_a_later_block_is_valid():
    """파서는 첫 블록만 본다 — 그것이 불완전하면 뒤의 완전한 블록을 써야 한다."""
    broken = {"architecture": {"summary": "잘림"}}
    complete = {"architecture": _ARCH, "components": [_COMPONENT]}

    got = _salvage(_result(None, broken, complete), Design)

    assert got is not None and got.architecture.summary == "단일 Node 백엔드"


def test_returns_none_when_nothing_validates():
    """구제 불가면 None — 호출부가 retry_hint로 1회 재시도한다."""
    assert _salvage(_result(None, {"architecture": {"summary": "s"}}), Design) is None


def test_no_schema_keeps_old_behaviour():
    """schema를 안 주면 구제하지 않는다 — 기존 호출부의 동작이 바뀌지 않는다."""
    complete = {"architecture": _ARCH, "components": [_COMPONENT]}

    assert _salvage(_result(None, complete), None) is None
