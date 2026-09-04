"""진행상황 한 줄 — 양식은 001/09-출력양식.md가 정본이다.

`cli.py`는 `stream_mode="updates"`라 노드가 끝난 뒤에만 개입한다 — 노드 안의 툴 루프와
항목별 루프는 여기서만 보인다.

스피너·커서 되감기를 쓰지 않는다: 병렬 단계가 서로를 덮어쓰고 승인 프롬프트가 stdin을
읽어 화면을 다툰다. 줄 단위로 완결된 출력만 낸다.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import typer
from langchain_core.tools import StructuredTool

if TYPE_CHECKING:
    from collections.abc import Iterator

    from langchain_core.tools import BaseTool

_MARK = "  · "
_ARG_CHARS = 60

# 툴마다 인자 이름이 다르다. 화면에 보여줄 값을 이 순서로 찾는다
_ARG_KEYS = ("text", "query", "name", "repo")

# `asyncio.Lock`이 아닌 이유: 상태를 만지는 것이 이벤트 루프 스레드와 `to_thread`
# 워커 둘이고, 모듈 전역이라 단계마다 새로 만들 수 없는데 asyncio 락은 처음 만진
# 루프에 묶인다 (단계마다 `asyncio.run()`으로 루프를 새로 연다)
_lock = threading.Lock()
# bool이 아니라 카운터 — 중첩되면 안쪽 종료가 조기 flush한다
_hold_depth = 0
_pending: list[str] = []


def step(message: str, *, subject: str | None = None) -> None:
    """진행 한 줄. 병렬 구간에서는 `subject`(요소명·후보명)를 앞에 붙인다."""
    body = f"{subject} — {message}" if subject else message
    line = f"{_MARK}{body}"
    # 평시 출력도 락 안에서 한다 — 밖에서 하면 판단과 echo 사이에 보류가 시작돼
    # 질문 바로 뒤에 한 줄이 새는 경쟁이 남는다
    with _lock:
        if _hold_depth:
            _pending.append(line)
        else:
            typer.echo(line)


@contextmanager
def while_asking() -> Iterator[None]:
    """사람이 답하는 동안 진행 줄을 보류한다 — stdin을 읽는 함수가 직접 감싼다.

    공통 경로가 아니라 호출부에 두는 이유는 묻지 않는 `auto_approve`가 화면을 독점할
    근거가 없기 때문이다. 그래서 분기 코드가 필요 없다.

    락은 마이크로초만 잡는다 — 프롬프트 내내 잡으면 같은 스레드의 `step()`이 비재진입
    락에 스스로 막힌다. `finally`가 없으면 `NonInteractive` 경로에서 남은 실행이
    전부 조용해진다.
    """
    global _hold_depth
    with _lock:
        _hold_depth += 1
    try:
        yield
    finally:
        with _lock:
            _hold_depth -= 1
            if _hold_depth == 0 and _pending:
                # 락 안에서 flush한다 — 밖에서 하면 해제 후 도착한 줄이 먼저 찍힌다
                typer.echo("\n".join(_pending))
                _pending.clear()


def _arg_hint(args: dict) -> str:
    for key in _ARG_KEYS:
        value = args.get(key)
        if value:
            shown = str(value)
            if len(shown) > _ARG_CHARS:
                shown = shown[:_ARG_CHARS] + "…"
            return f' "{shown}"'
    return ""


def wrap_progress(tool: BaseTool, *, subject: str | None = None) -> StructuredTool:
    """툴 호출을 한 줄로 알린다.

    `wrap_web_search`보다 **안쪽에** 감싼다 — 반대로 감싸면 승인이 거부돼 나가지도
    않은 검색이 화면에 남는다.
    """

    async def announced(**kwargs: Any) -> Any:
        step(f"{tool.name}{_arg_hint(kwargs)}", subject=subject)
        return await tool.ainvoke(kwargs)

    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        coroutine=announced,
        metadata=tool.metadata,
    )


def wrap_all(tools: dict[str, BaseTool], *, subject: str | None = None) -> dict:
    return {name: wrap_progress(t, subject=subject) for name, t in tools.items()}
