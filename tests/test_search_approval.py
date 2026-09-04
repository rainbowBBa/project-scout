"""웹검색 승인 게이트의 배선을 검사한다 — LLM도 네트워크도 쓰지 않는다.

검증하는 주장: **거부하면 egress가 실제로 일어나지 않는다** (불변식 14). 승인 문구만
띄우고 툴이 그냥 나가면 보안 기능이 장식이 된다.
"""

import asyncio
import threading
from contextlib import contextmanager
from typing import ClassVar

import pytest
import typer
from langchain_core.tools import StructuredTool
from scout import approval, progress
from scout.agentkit import collect_tool_calls
from scout.approval import (
    APPROVAL_NOTICE,
    Approval,
    NonInteractive,
    SearchGate,
    auto_approve,
    default_approve,
    wrap_web_search,
)
from scout.progress import step, while_asking
from scout.stages.search import facts_for_candidate

# Event.wait에 항상 상한을 준다 — 구현이 깨졌을 때 스위트가 매달리는 대신 실패해야 한다.
_TIMEOUT = 5.0


class _SpyTool:
    """원본 MCP 툴 대역. 호출 자체가 egress다."""

    name = "web_search"
    description = "웹 검색"
    args_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {"query": {"type": "string"}, "n": {"type": "integer"}},
        "required": ["query"],
    }
    metadata = None

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def ainvoke(self, args: dict) -> str:
        self.calls.append(args)
        return '{"results": []}'


def _wrapped(approve) -> tuple[StructuredTool, _SpyTool, SearchGate]:
    spy = _SpyTool()
    gate = SearchGate(approve=approve)
    return wrap_web_search(spy, gate), spy, gate


async def test_rejection_blocks_egress():
    tool, spy, _ = _wrapped(lambda q: Approval(False, "사내 프로젝트명이 들어감"))

    result = await tool.ainvoke({"query": "acme 사내 채팅 websocket"})

    assert spy.calls == [], "거부했는데 원본 툴이 호출됐다 — egress가 일어났다"
    assert "사내 프로젝트명이 들어감" in result, "거부 사유가 에이전트에 돌아가지 않는다"


async def test_approval_passes_args_through():
    tool, spy, _ = _wrapped(lambda q: Approval(True))

    await tool.ainvoke({"query": "websocket server node", "n": 3})

    assert spy.calls == [{"query": "websocket server node", "n": 3}]


async def test_repeated_rejection_blocks_further_search():
    tool, spy, gate = _wrapped(lambda q: Approval(False, "안 됨"))

    for i in range(5):
        await tool.ainvoke({"query": f"질의 {i}"})

    assert gate.blocked, "거부가 반복돼도 차단되지 않으면 에이전트가 무한히 되묻는다"
    assert spy.calls == []


async def test_budget_caps_approved_searches():
    """예산이 없으면 에이전트가 한 결정 지점에 열 번 넘게 검색한다."""
    spy = _SpyTool()
    gate = SearchGate(approve=lambda q: Approval(True))
    tool = wrap_web_search(spy, gate, budget=2)

    for i in range(5):
        await tool.ainvoke({"query": f"질의 {i}"})

    assert len(spy.calls) == 2, "예산을 넘겨 검색이 나갔다"


async def test_rejection_does_not_consume_budget():
    spy = _SpyTool()
    approvals = iter([Approval(False, "다시"), Approval(True), Approval(True)])
    gate = SearchGate(approve=lambda q: next(approvals))
    tool = wrap_web_search(spy, gate, budget=2)

    for i in range(3):
        await tool.ainvoke({"query": f"질의 {i}"})

    assert len(spy.calls) == 2, "거부가 예산을 깎으면 재질의할 기회가 사라진다"


async def test_non_interactive_blocks_without_prompting():
    def refuse(query: str) -> Approval:
        raise NonInteractive

    tool, spy, gate = _wrapped(refuse)

    await tool.ainvoke({"query": "무엇이든"})
    await tool.ainvoke({"query": "두 번째"})

    assert spy.calls == []
    assert gate.blocked
    assert any("비대화형" in note for note in gate.notes)


def test_approval_notice_names_the_query():
    """질의가 사람에게 보여야 한다 — 감추면 게이트가 장식이 된다."""
    notice = APPROVAL_NOTICE.format(query="socket.io alternative")

    assert "socket.io alternative" in notice
    assert notice.startswith("  ? "), "사람에게 묻는 줄은 열 2의 `? `로 시작한다"


# ── 사실은 툴 원본에서만 나온다 ──────────────────────────────────────────


class _FakeAI:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls


class _FakeToolMessage:
    tool_calls = None

    def __init__(self, tool_call_id, content, name=""):
        self.tool_call_id = tool_call_id
        self.content = content
        self.name = name

    def text(self):
        return self.content


def test_facts_come_from_tool_payload_not_llm_text(monkeypatch):
    """judge가 인용할 사실은 ToolMessage 원본에서 나온다 (불변식 13)."""
    import scout.agentkit as agentkit

    monkeypatch.setattr(agentkit, "ToolMessage", _FakeToolMessage)

    messages = [
        _FakeAI([{"id": "c1", "name": "npm_package", "args": {"name": "socket.io"}}]),
        _FakeToolMessage(
            "c1",
            '{"name": "socket.io", "latest_version": "4.8.1", '
            '"last_release": "2026-08-20", "license": "MIT"}',
        ),
    ]

    calls = collect_tool_calls(messages)
    facts = facts_for_candidate(calls, "socket.io", now="2026-09-03T00:00:00Z")

    by_id = {f.id: f.value for f in facts}
    assert by_id["npm.last_release"] == "2026-08-20"
    assert by_id["npm.license"] == "MIT"


def test_facts_are_not_attached_to_unrelated_candidate(monkeypatch):
    import scout.agentkit as agentkit

    monkeypatch.setattr(agentkit, "ToolMessage", _FakeToolMessage)

    messages = [
        _FakeAI([{"id": "c1", "name": "npm_package", "args": {"name": "socket.io"}}]),
        _FakeToolMessage("c1", '{"name": "socket.io", "license": "MIT"}'),
    ]
    calls = collect_tool_calls(messages)

    assert facts_for_candidate(calls, "ws", now="2026-09-03T00:00:00Z") == []


# ── 묻는 동안 화면을 독점한다 (001/09-출력양식.md) ──────────────────────


def test_default_approve_holds_progress_lines(monkeypatch, capsys):
    """보류 창이 `default_approve`에 있다 — 스레드 없이 결정적으로 검사한다."""

    def confirm(_text, default=False):
        step("npm_package \"jose\"", subject="인증")
        assert capsys.readouterr().out == "", "묻는 중에 진행 줄이 질문을 밀어냈다"
        return True

    monkeypatch.setattr(typer, "confirm", confirm)

    assert default_approve("PG LISTEN NOTIFY vs Redis").approved
    assert capsys.readouterr().out == '  · 인증 — npm_package "jose"\n'


def test_auto_approve_does_not_hold(monkeypatch, capsys):
    """자동 승인은 창을 열지 않는다 — 답할 사람이 없으면 화면을 독점할 근거가 없다."""
    opened: list[str] = []

    @contextmanager
    def spy():
        opened.append("열림")
        yield

    monkeypatch.setattr(approval, "while_asking", spy)

    auto_approve("socket.io redis adapter")

    assert opened == [], "자동 승인이 화면을 독점했다"
    assert "자동 승인" in capsys.readouterr().out


def test_non_interactive_still_flushes(monkeypatch, capsys):
    """`finally` 누락 회귀의 방어선 — 예외 경로에서 flush를 빼먹으면 남은 실행이 조용해진다."""

    def confirm(_text, default=False):
        step("보류된 줄")
        raise EOFError

    monkeypatch.setattr(typer, "confirm", confirm)

    with pytest.raises(NonInteractive):
        default_approve("무엇이든")

    assert capsys.readouterr().out == "  · 보류된 줄\n", "예외 경로에서 줄이 사라졌다"
    assert progress._hold_depth == 0, "예외 경로에서 창이 닫히지 않았다"


async def test_second_question_never_overlaps_the_first(capsys):
    """질문은 한 번에 하나다 — `check`가 `_lock`을 프롬프트 내내 잡는다.

    임계구역을 좁히면 조용히 깨지는 자리라 고정한다.
    """
    order: list[str] = []
    first_asking = threading.Event()
    release_first = threading.Event()

    def approve(query: str) -> Approval:
        order.append(f"묻기 시작 {query}")
        with while_asking():
            if query == "첫째":
                first_asking.set()
                assert release_first.wait(_TIMEOUT), "둘째가 확인을 마치지 못했다"
        order.append(f"답 완료 {query}")
        return Approval(True)

    gate = SearchGate(approve=approve)

    async def observer() -> None:
        assert await asyncio.to_thread(first_asking.wait, _TIMEOUT)
        # 첫 질문이 열려 있는 지금, 둘째는 _lock에 막혀 시작조차 안 됐어야 한다
        assert order == ["묻기 시작 첫째"], f"둘째 질문이 겹쳤다: {order}"
        release_first.set()

    await asyncio.gather(gate.check("첫째"), gate.check("둘째"), observer())

    assert order == [
        "묻기 시작 첫째",
        "답 완료 첫째",
        "묻기 시작 둘째",
        "답 완료 둘째",
    ], f"질문이 직렬로 흐르지 않았다: {order}"
