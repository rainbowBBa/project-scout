"""웹검색 승인 게이트의 배선을 검사한다 — LLM도 네트워크도 쓰지 않는다.

검증하는 주장: **거부하면 egress가 실제로 일어나지 않는다.** 승인 문구만 띄우고
그 뒤로 툴이 그냥 나가버리면 보안 기능이 장식이 된다. `test_necessity_wiring`과 같은
성격이다 — 판단이 아니라 배선을 본다.
"""

from typing import ClassVar

from langchain_core.tools import StructuredTool
from scout.agentkit import collect_tool_calls
from scout.approval import (
    APPROVAL_NOTICE,
    Approval,
    NonInteractive,
    SearchGate,
    wrap_web_search,
)
from scout.stages.search import facts_for_candidate


class _SpyTool:
    """원본 MCP 툴 대역. 호출되면 기록한다 — 호출 자체가 egress다."""

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
    """예산이 없으면 에이전트가 한 요소에 15번씩 검색해 승인 프롬프트를 그만큼 띄운다."""
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
    assert APPROVAL_NOTICE.format(query="socket.io alternative") == (
        '"socket.io alternative" 키워드로 인터넷 검색을 하려고 합니다. 확인 바랍니다.'
    )


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
    """judge가 인용할 사실은 ToolMessage 원본에서 나와야 한다 (불변식 4의 뿌리)."""
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
