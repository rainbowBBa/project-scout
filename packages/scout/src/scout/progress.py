"""진행상황 한 줄 — "지금 무엇을 하는 중인가"만 알린다 (001/09-출력양식.md).

`cli.py`는 `stream_mode="updates"`라 **노드가 끝난 뒤에만** 개입한다. 그래서 노드 안의
툴 루프(`design` 최대 10 superstep · `search` 16)와 항목별 루프(`verify` 후보당 ·
`evaluate` 요소당)가 보이지 않고, `design`부터 몇 분씩 화면이 멈춘 것처럼 보였다.

스피너·커서 되감기를 쓰지 않는다 — `search`·`verify`가 `asyncio.gather`로 병렬이라
서로를 덮어쓰고, `web_search` 승인이 stdin을 읽어 화면을 다툰다. **줄 단위로 완결된
출력만** 낸다. 부수 효과로 로그로 리다이렉트해도 그대로 읽힌다.

`·` 줄끼리 섞이는 건 막지 않는다 — 어느 항목의 줄인지 `subject`로 보이게 할 뿐이다.
다만 `·`가 `?`를 밀어내는 것은 막는다: 사람이 답하는 동안은 `while_asking()`이 진행
줄을 붙잡아 둔다. `?`는 화면 앞에 있어야 하고 `·`는 자리를 비워도 된다는 정본의
우선순위를 집행하는 장치다 (001/09-출력양식.md).
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

# 열 2의 `· ` — "기다리면 되는 것". `? `(내가 답할 차례)·`라벨: `(결과)와 구분된다.
_MARK = "  · "
_ARG_CHARS = 60

# 툴마다 인자 이름이 다르다. 화면에 보여줄 값을 이 순서로 찾는다.
_ARG_KEYS = ("text", "query", "name", "repo")

# ★ `threading.Lock`이다. `asyncio.Lock`이 안 되는 이유가 셋이고 각각 결정적이다 —
# (1) 창을 여는 `default_approve`는 `asyncio.to_thread` 워커에서 도는 동기 함수라
# `await`할 수 없다 (2) `asyncio.Lock`은 스레드 안전하지 않은데 여기 상태를 만지는 건
# 이벤트 루프 스레드와 그 워커 둘이다 (3) 모듈 전역이라 단계마다 새로 만들 수 없는데
# `asyncio.Lock`은 처음 만진 루프에 묶인다 — `design_node`·`search_node`가 각각
# `asyncio.run()`으로 루프를 열므로 두 번째 단계에서 깨진다 (approval.py docstring이
# 게이트 인스턴스를 단계마다 새로 만드는 이유로 적어둔 것과 같은 함정).
_lock = threading.Lock()
# 보류 깊이. bool이 아니라 카운터인 이유는 중첩 시 안쪽 종료가 조기 flush하는 버그군을
# 아예 없애기 위해서다 — 비용은 int 하나다.
_hold_depth = 0
_pending: list[str] = []


def step(message: str, *, subject: str | None = None) -> None:
    """진행 한 줄. 병렬 구간에서는 `subject`(요소명·후보명)를 앞에 붙인다 —
    줄이 섞이는 건 막을 수 없으니 어느 항목의 줄인지 보이게 한다.

    사람이 답하는 중이면 찍지 않고 `_pending`에 담는다 — `while_asking()` 참고.
    """
    body = f"{subject} — {message}" if subject else message
    line = f"{_MARK}{body}"
    # 평시 출력도 락 안에서 한다. 밖에서 하면 "판단 → (그 사이 보류 시작) → echo" 창이
    # 열려 질문 바로 뒤에 한 줄이 새는 경쟁이 남는다.
    with _lock:
        if _hold_depth:
            _pending.append(line)
        else:
            typer.echo(line)


@contextmanager
def while_asking() -> Iterator[None]:
    """사람이 답하는 동안 진행 줄을 보류한다 — **stdin을 읽는 함수가 직접 감싼다.**

    공통 경로(`SearchGate.check`)가 아니라 호출부에 있는 이유: 보류의 근거가 "답할
    사람이 화면 앞에 있다"이므로, 사람에게 묻지 않는 `auto_approve`는 화면을 독점할
    이유가 없다. 창을 여는 자리를 stdin 읽는 쪽으로 내리면 그 분기가 코드에서 사라진다.

    ★ **보류는 플래그이고 락은 마이크로초다.** 락을 프롬프트 내내 잡으면 같은 스레드에서
    도는 `auto_approve`의 `step()`이 비재진입 락에 스스로 막힌다.

    ★ **`try/finally`가 필수다.** `default_approve`는 `NonInteractive`를 던진다 — 예외
    경로에서 flush를 빼먹으면 남은 실행 전체가 조용해진다(원래 버그보다 나쁘다).
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
                # flush를 락 안에서 한다 — 밖에서 하면 해제 후 도착한 줄이 밀린 줄보다
                # 먼저 찍히는 역전이 생기고, 막으려면 재드레인 루프와 굶주림 처리가 붙는다.
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
