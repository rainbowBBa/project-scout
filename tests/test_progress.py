"""진행 표시(`progress.py`)의 배선을 검사한다 — LLM도 네트워크도 쓰지 않는다.

`wrap_web_search`와 같은 위험군이다. 검사하는 주장은 하나다 —
**진행 표시가 조사를 망치지 않는다.** 래퍼가 원본 호출을 그대로 통과시키지 않으면
화면만 예뻐지고 dossier가 비게 된다.
"""

from typing import ClassVar

from scout.approval import Approval, SearchGate, wrap_web_search
from scout.progress import step, wrap_progress


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
