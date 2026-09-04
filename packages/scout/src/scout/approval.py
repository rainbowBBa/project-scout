"""웹검색 사람 승인 게이트 — `design`과 `search`가 공유한다.

`scout_net_mcp`가 아니라 앱 쪽에 있다 (001/04-아키텍처.md "앱측 승인 게이트").
allowlist가 *어디로* 나가는지를 막는다면 이 게이트는 *무엇이* 나가는지를 막는다.

단계별 모듈이 아니라 여기 있는 이유는 stage → stage import를 만들지 않기 위해서다.
게이트 **인스턴스**는 단계마다 새로 만든다 — `design_node`와 `search_node`가 각각
`asyncio.run()`으로 이벤트 루프를 새로 열기 때문에 `SearchGate._lock`을 공유하면
락이 다른 루프에 묶인다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import typer
from langchain_core.tools import StructuredTool

from scout.progress import step, while_asking

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

# 기본값이자 테스트의 기준선. 프로덕션은 Settings 값을 인자로 넘긴다 — 모듈 상수를
# 직접 읽으면 개발자 로컬 `.env`가 테스트 결과를 바꾸고, `.env`는 커밋되지 않아
# 재현도 안 된다 (불변식 10).
DEFAULT_MAX_REJECTIONS = 3

# 승인되는 웹검색 상한. 없으면 에이전트가 한 요소에 15번씩 검색해 사람에게 승인
# 프롬프트를 그만큼 띄운다 (실측). `search`는 요소당 이 값을 쓰고, `design`은 실행
# 전체에 3회를 쓴다 — 설계는 요소별로 펼치지 않고 한 번 돌기 때문이다.
DEFAULT_WEB_SEARCH_BUDGET = 5

# 열 2의 `? ` — 사람에게 묻는 줄 (001/09-출력양식.md). `: `는 typer가 붙인다.
APPROVAL_NOTICE = '  ? 인터넷 검색 "{query}" — 허용할까요?'


@dataclass
class Approval:
    approved: bool
    reason: str = ""


Approve = Callable[[str], Approval]


class NonInteractive(Exception):
    """대화형 입력이 불가능한 환경(파이프·CI)에서 stdin이 즉시 EOF일 때."""


def default_approve(query: str) -> Approval:
    """묻는 동안 화면을 독점한다 — `while_asking()`이 병렬 요소의 진행 줄을 붙잡는다.

    이 함수가 `search`에서 `asyncio.to_thread` 워커로 도는 동안 이벤트 루프는 계속
    돌기 때문에(`SearchGate.check` 참고), 창이 없으면 다른 요소의 `·` 줄이 질문을
    화면 위로 밀어낸다. 승인과 거부 사유가 **한 창 안**에 들어간다.
    """
    with while_asking():
        try:
            if typer.confirm(APPROVAL_NOTICE.format(query=query), default=False):
                return Approval(approved=True)
            reason = typer.prompt("  ? 거부 사유", default="", show_default=False)
        except EOFError, typer.Abort:  # PEP 758 (3.14) — 괄호 없는 다중 예외
            raise NonInteractive from None
    return Approval(approved=False, reason=reason.strip() or "(사유 없음)")


def auto_approve(query: str) -> Approval:
    """`--auto-approve-search` 전용. 질문이 아니므로 `·` 진행 줄이다.

    무엇이 나갔는지는 그대로 찍는다 — 승인을 건너뛴다고 내용을 감추면 게이트의
    의미가 준다.

    `while_asking()`을 쓰지 않는다 — 답할 사람이 없으니 화면을 독점할 근거가 없다.
    """
    step(f'인터넷 검색 "{query}" — 자동 승인')
    return Approval(approved=True)


_REJECTED_TEMPLATE = (
    "사용자가 이 검색을 거부했습니다. 사유: {reason}\n"
    "이 사유를 반영해 질의를 고쳐 다시 시도하거나, 웹검색 없이 진행하세요. "
    "같은 질의를 그대로 다시 보내지 마세요."
)
_BLOCKED_MESSAGE = (
    "웹검색을 더는 쓸 수 없습니다. 지금까지 모은 사실만으로 결론을 내세요."
)
# 예산은 단계마다 다르므로 숫자를 문구에 굳히지 않는다.
_BUDGET_TEMPLATE = (
    "웹검색 예산({budget}회)을 다 썼습니다. 지금까지 모은 사실만으로 결론을 내세요."
)


@dataclass
class SearchGate:
    """한 단계 동안의 웹검색 승인 상태. 거부 횟수가 한도를 넘으면 차단한다."""

    approve: Approve
    max_rejections: int = DEFAULT_MAX_REJECTIONS
    blocked: bool = False
    rejections: int = 0
    notes: list[str] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def check(self, query: str) -> Approval:
        async with self._lock:
            if self.blocked:
                return Approval(False, "이 실행에서는 웹검색을 쓸 수 없습니다")
            try:
                # 프롬프트를 스레드로 넘긴다 — 이벤트 루프를 막으면 다른 요소의
                # in-flight HTTP가 응답을 못 읽고 타임아웃에 걸린다. 그래서 루프가 계속
                # 도는 동안의 **화면 독점**은 여기가 아니라 `default_approve`의
                # `while_asking()`이 맡는다 (001/09-출력양식.md).
                #
                # ★ 이 락이 프롬프트 **내내** 잡혀 있어야 한다. 두 번째 요소의 check()가
                # 여기서 막혀 질문을 아예 시작하지 못하는 것이 곧 "질문은 한 번에
                # 하나"의 근거다 — 임계구역을 좁히면 두 질문이 화면에서 겹친다.
                approval = await asyncio.to_thread(self.approve, query)
            except NonInteractive:
                self.blocked = True
                self.notes.append("비대화형 실행 — 웹검색 승인 불가로 차단됨")
                return Approval(False, "비대화형 실행이라 승인할 사람이 없습니다")

            if approval.approved:
                return approval

            self.rejections += 1
            self.notes.append(f"웹검색 거부: {query} — {approval.reason}")
            if self.rejections >= self.max_rejections:
                self.blocked = True
                self.notes.append(f"웹검색 거부 {self.max_rejections}회 — 이후 차단됨")
            return approval


def wrap_web_search(
    tool: BaseTool, gate: SearchGate, *, budget: int = DEFAULT_WEB_SEARCH_BUDGET
) -> StructuredTool:
    """`web_search`를 승인 게이트로 감싼다. 거부되면 원본을 호출하지 않는다 — egress 0.

    `budget`은 승인된 검색 횟수 상한이다. 거부는 예산을 쓰지 않는다 — 거부 반복은
    `SearchGate.rejections`가 따로 막는다.

    `args_schema`는 MCP가 준 raw JSON Schema dict 그대로 물려준다. 원본은
    `response_format="content_and_artifact"`라 2-튜플을 돌려주지만, 여기서는
    `ainvoke`로 content만 받아 문자열 하나로 통일한다 — 거부 시엔 사유 문자열을
    같은 자리에 돌려줘야 하기 때문이다.
    """
    remaining = budget

    async def gated(**kwargs: Any) -> Any:
        nonlocal remaining
        if remaining <= 0:
            return _BUDGET_TEMPLATE.format(budget=budget)
        approval = await gate.check(str(kwargs.get("query", "")))
        if approval.approved:
            remaining -= 1
            return await tool.ainvoke(kwargs)
        if gate.blocked:
            return _BLOCKED_MESSAGE
        return _REJECTED_TEMPLATE.format(reason=approval.reason)

    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        coroutine=gated,
        metadata=tool.metadata,
    )
