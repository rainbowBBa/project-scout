"""진행상황 한 줄 — "지금 무엇을 하는 중인가"만 알린다 (001/09-출력양식.md).

`cli.py`는 `stream_mode="updates"`라 **노드가 끝난 뒤에만** 개입한다. 그래서 노드 안의
툴 루프(`design` 최대 10 superstep · `search` 16)와 항목별 루프(`verify` 후보당 ·
`evaluate` 요소당)가 보이지 않고, `design`부터 몇 분씩 화면이 멈춘 것처럼 보였다.

스피너·커서 되감기를 쓰지 않는다 — `search`·`verify`가 `asyncio.gather`로 병렬이라
서로를 덮어쓰고, `web_search` 승인이 stdin을 읽어 화면을 다툰다. **줄 단위로 완결된
출력만** 낸다. 부수 효과로 로그로 리다이렉트해도 그대로 읽힌다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import typer
from langchain_core.tools import StructuredTool

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

# 열 2의 `· ` — "기다리면 되는 것". `? `(내가 답할 차례)·`라벨: `(결과)와 구분된다.
_MARK = "  · "
_ARG_CHARS = 60

# 툴마다 인자 이름이 다르다. 화면에 보여줄 값을 이 순서로 찾는다.
_ARG_KEYS = ("text", "query", "name", "repo")


def step(message: str, *, subject: str | None = None) -> None:
    """진행 한 줄. 병렬 구간에서는 `subject`(요소명·후보명)를 앞에 붙인다 —
    줄이 섞이는 건 막을 수 없으니 어느 항목의 줄인지 보이게 한다.
    """
    body = f"{subject} — {message}" if subject else message
    typer.echo(f"{_MARK}{body}")


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
    """툴 호출을 한 줄로 알린다. `approval.wrap_web_search`와 같은 패턴이다.

    ★ **`wrap_web_search`보다 안쪽에 감싼다.** 그래야 승인이 거부됐을 때 진행 줄이
    찍히지 않는다 — 반대로 감싸면 나가지도 않은 검색이 화면에 남는다.
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
