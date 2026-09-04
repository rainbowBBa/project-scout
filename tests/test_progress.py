"""진행 표시(`progress.py`)의 배선을 검사한다 — LLM도 네트워크도 쓰지 않는다.

`wrap_web_search`와 같은 위험군이다. 검사하는 주장이 둘이다 —

1. **진행 표시가 조사를 망치지 않는다.** 래퍼가 원본 호출을 그대로 통과시키지 않으면
   화면만 예뻐지고 dossier가 비게 된다.
2. **사람이 답하는 동안 진행 줄이 질문을 밀어내지 않는다.** `?`는 화면 앞에 있어야 하고
   `·`는 자리를 비워도 된다 (001/09-출력양식.md). 보류했던 줄은 **버리지 않고** 답변 뒤에
   순서대로 전부 찍는다 — 로그로 리다이렉트했을 때 기록이 남아야 한다.
"""

import asyncio
import threading
from typing import ClassVar

import pytest
from scout import progress
from scout.approval import Approval, SearchGate, wrap_web_search
from scout.progress import step, while_asking, wrap_progress

# Event.wait에 항상 상한을 준다 — 구현이 깨졌을 때 스위트가 매달리는 대신 실패해야 한다.
_TIMEOUT = 5.0


@pytest.fixture(autouse=True)
def _no_leaked_hold():
    """창을 열어놓고 죽은 테스트가 이후 전부를 조용하게 만드는 연쇄 실패를 막는다.

    모듈 전역 상태의 유일한 실질 위험이 이것이고, 그때 원인이 화면에 안 보인다.
    """
    yield
    assert progress._hold_depth == 0, "보류 창이 열린 채 남았다"
    assert progress._pending == [], "flush되지 않은 진행 줄이 남았다"


class _SpyTool:
    """원본 MCP 툴 대역. 호출되면 기록한다 — 호출 자체가 egress다."""

    name = "npm_search"
    description = "npm 검색"
    args_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }
    metadata = None

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def ainvoke(self, args: dict) -> str:
        self.calls.append(args)
        return '{"results": []}'


async def test_passes_the_call_through_untouched():
    """★ 진행 표시가 조사를 바꾸지 않는다 — 인자도 반환값도 그대로다."""
    spy = _SpyTool()
    tool = wrap_progress(spy)

    result = await tool.ainvoke({"text": "socket.io node.js websocket server"})

    assert spy.calls == [{"text": "socket.io node.js websocket server"}]
    assert result == '{"results": []}'


async def test_prints_one_complete_line_with_the_argument(capsys):
    spy = _SpyTool()

    await wrap_progress(spy).ainvoke({"text": "ws websocket library node"})

    out = capsys.readouterr().out
    assert out.count("\n") == 1, "줄 단위로 완결돼야 한다 — 병렬 구간에서 섞인다"
    assert out.startswith("  · "), "진행 줄은 열 2의 `· `로 시작한다"
    assert "npm_search" in out
    assert "ws websocket library node" in out


async def test_subject_comes_first_in_parallel_stages(capsys):
    """`search`·`verify`는 병렬이라 줄이 섞인다 — 어느 항목인지 앞에 보여야 한다."""
    spy = _SpyTool()

    await wrap_progress(spy, subject="실시간 메시지 전달").ainvoke({"text": "x"})

    out = capsys.readouterr().out
    assert out.startswith("  · 실시간 메시지 전달 — ")


async def test_rejected_search_prints_no_progress_line(capsys):
    """★ 감싸는 순서를 고정한다 — wrap_progress가 안쪽, wrap_web_search가 바깥쪽.

    반대로 감싸면 승인이 거부돼 **나가지도 않은 검색**이 진행 줄에 남는다.
    """
    spy = _SpyTool()
    spy.name = "web_search"
    gate = SearchGate(approve=lambda q: Approval(False, "고유명사를 빼세요"))
    tool = wrap_web_search(wrap_progress(spy), gate)

    result = await tool.ainvoke({"query": "acme 사내 채팅"})

    assert spy.calls == [], "거부했는데 원본이 호출됐다"
    assert capsys.readouterr().out == "", "나가지 않은 검색이 진행 줄에 남았다"
    assert "고유명사를 빼세요" in result


def test_step_without_subject(capsys):
    step("설계 추출")

    assert capsys.readouterr().out == "  · 설계 추출\n"


# ── 묻는 동안 진행 줄을 보류한다 ────────────────────────────────────────


def test_no_lines_while_asking(capsys):
    """★ 질문이 답을 기다리는 동안 `·` 줄은 화면에 나오지 않는다."""
    with while_asking():
        step("npm_package \"jose\"", subject="인증")
        step("github_repo_health \"postgres\"", subject="저장소")

        assert capsys.readouterr().out == "", "묻는 중에 진행 줄이 질문을 밀어냈다"


def test_all_held_lines_print_in_order_after(capsys):
    """★ 보류한 줄은 버리지 않는다 — 답변 뒤에 순서대로 전부 찍힌다."""
    with while_asking():
        step("A", subject="요소1")
        step("B", subject="요소2")

    out = capsys.readouterr().out
    assert out == "  · 요소1 — A\n  · 요소2 — B\n"
    assert out.count("\n") == 2, "줄 단위로 완결돼야 한다 — 병렬 구간에서 섞인다"


def test_nested_hold_does_not_flush_early(capsys):
    """중첩되면 안쪽 종료로 찍히지 않는다 — 재진입 카운터의 증거."""
    with while_asking():
        step("바깥")
        with while_asking():
            step("안쪽")
        assert capsys.readouterr().out == "", "안쪽 창이 닫히자 조기 flush됐다"

    assert capsys.readouterr().out == "  · 바깥\n  · 안쪽\n"


def test_line_after_flush_comes_last(capsys):
    """flush 뒤에 발행한 줄이 밀린 줄보다 앞서지 않는다."""
    with while_asking():
        step("보류된 줄")
    step("나중 줄")

    assert capsys.readouterr().out == "  · 보류된 줄\n  · 나중 줄\n"


async def test_progress_is_held_while_another_component_asks(capsys):
    """★ 실제 토폴로지 — 승인 프롬프트는 워커 스레드, 진행 줄은 이벤트 루프에서 온다.

    `sleep` 없이 `Event` 핸드셰이크만 쓴다. 이 테스트가 없으면 장치가 `step()`
    단위로만 검증되고, **두 스레드가 같은 stdout을 다투는 실제 상황**은 안 잡힌다.
    """
    asking = threading.Event()
    answered = threading.Event()

    def approve(query: str) -> Approval:
        with while_asking():
            asking.set()
            assert answered.wait(_TIMEOUT), "형제 태스크가 진행 줄을 내지 못했다"
        return Approval(True)

    gate = SearchGate(approve=approve)

    async def sibling() -> None:
        assert await asyncio.to_thread(asking.wait, _TIMEOUT), "프롬프트가 열리지 않았다"
        step("npm_package \"jose\"", subject="인증")
        step("npm_package \"pg\"", subject="저장소")
        assert capsys.readouterr().out == "", "묻는 중에 다른 요소의 줄이 찍혔다"
        answered.set()

    approval, _ = await asyncio.gather(gate.check("PG LISTEN NOTIFY vs Redis"), sibling())

    assert approval.approved
    out = capsys.readouterr().out
    assert out == '  · 인증 — npm_package "jose"\n  · 저장소 — npm_package "pg"\n'
