"""search 단계 — ReAct 에이전트가 툴을 골라 후보를 찾고 dossier를 모은다.

요소마다 `langchain.agents.create_agent` 하나를 돌린다 (001/stages/2-search.md). 에이전트는
**어떤 툴을 부를지만** 정한다 — `Fact.value`는 에이전트가 쓴 문장이 아니라
`ToolMessage`의 원본 payload에서 코드가 뽑는다. 이 경계가 무너지면 judge가 인용하는
dossier 자체가 LLM 생성물이 되어 불변식 4가 지탱하던 "judge는 사실을 지어낼 수 없다"가
뿌리에서 깨진다.

`web_search`는 사람 승인을 거친다 — 거부되면 원본 툴을 호출하지 않으므로 egress가
일어나지 않고, 거부 사유가 툴 결과로 에이전트에 돌아가 질의를 고쳐 재시도한다.
LangGraph `interrupt()`를 쓰지 않는 이유는 2-search.md "왜 interrupt()가 아닌가" 참고 —
승인 콜러블이 나중에 `interrupt()`로 갈아끼울 이음매다.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import typer
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool

from scout import store
from scout.llm import invoke_structured
from scout.mcp_client import make_mcp_client
from scout.prompts import (
    SEARCH_AGENT_SYSTEM_PROMPT,
    SEARCH_AGENT_TASK_PROMPT,
    SEARCH_EXTRACT_PROMPT,
    SEARCH_EXTRACT_RETRY_HINT,
)
from scout.schemas import Candidate, CandidateList, Fact

if TYPE_CHECKING:
    from langchain_aws import ChatBedrockConverse
    from langchain_core.messages import BaseMessage
    from langchain_core.tools import BaseTool

    from scout.schemas import Component, Interview
    from scout.state import ScoutState

_MAX_REJECTIONS = 3
_MAX_WEB_FACTS = 6
_RECURSION_LIMIT = 40
_TOOL_PAYLOAD_CHARS = 1200
# 요소당 승인되는 웹검색 상한. 없으면 에이전트가 한 요소에 15번씩 검색해
# 사람에게 승인 프롬프트를 그만큼 띄운다 (실측).
_MAX_WEB_SEARCHES = 5


# ── 승인 게이트 ───────────────────────────────────────────────────────────

APPROVAL_NOTICE = '"{query}" 키워드로 인터넷 검색을 하려고 합니다. 확인 바랍니다.'


@dataclass
class Approval:
    approved: bool
    reason: str = ""


Approve = Callable[[str], Approval]


class NonInteractive(Exception):
    """대화형 입력이 불가능한 환경(파이프·CI)에서 stdin이 즉시 EOF일 때."""


def default_approve(query: str) -> Approval:
    typer.echo("")
    typer.echo(APPROVAL_NOTICE.format(query=query))
    try:
        if typer.confirm("승인하시겠습니까?", default=False):
            return Approval(approved=True)
        reason = typer.prompt("거부 사유를 입력하세요", default="", show_default=False)
    except EOFError, typer.Abort:
        raise NonInteractive from None
    return Approval(approved=False, reason=reason.strip() or "(사유 없음)")


def auto_approve(query: str) -> Approval:
    """`--auto-approve-search` 전용. 무엇이 나갔는지는 그대로 찍는다."""
    typer.echo(APPROVAL_NOTICE.format(query=query) + " → 자동 승인")
    return Approval(approved=True)


_REJECTED_TEMPLATE = (
    "사용자가 이 검색을 거부했습니다. 사유: {reason}\n"
    "이 사유를 반영해 질의를 고쳐 다시 시도하거나, 웹검색 없이 진행하세요. "
    "같은 질의를 그대로 다시 보내지 마세요."
)
_BLOCKED_MESSAGE = (
    "웹검색을 더는 쓸 수 없습니다. 지금까지 모은 사실만으로 결론을 내세요."
)
_BUDGET_MESSAGE = (
    f"이 요소의 웹검색 예산({_MAX_WEB_SEARCHES}회)을 다 썼습니다. "
    "지금까지 모은 사실만으로 결론을 내세요."
)


@dataclass
class SearchGate:
    """실행 하나 동안의 웹검색 승인 상태. 거부 횟수가 한도를 넘으면 차단한다."""

    approve: Approve
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
                # in-flight HTTP가 응답을 못 읽고 타임아웃에 걸린다.
                approval = await asyncio.to_thread(self.approve, query)
            except NonInteractive:
                self.blocked = True
                self.notes.append("비대화형 실행 — 웹검색 승인 불가로 차단됨")
                return Approval(False, "비대화형 실행이라 승인할 사람이 없습니다")

            if approval.approved:
                return approval

            self.rejections += 1
            self.notes.append(f"웹검색 거부: {query} — {approval.reason}")
            if self.rejections >= _MAX_REJECTIONS:
                self.blocked = True
                self.notes.append(f"웹검색 거부 {_MAX_REJECTIONS}회 — 이후 차단됨")
            return approval


def wrap_web_search(
    tool: BaseTool, gate: SearchGate, *, budget: int = _MAX_WEB_SEARCHES
) -> StructuredTool:
    """`web_search`를 승인 게이트로 감싼다. 거부되면 원본을 호출하지 않는다 — egress 0.

    `budget`은 요소 하나가 쓸 수 있는 승인된 검색 횟수다. 거부는 예산을 쓰지 않는다 —
    거부 반복은 `SearchGate.rejections`가 따로 막는다.

    `args_schema`는 MCP가 준 raw JSON Schema dict 그대로 물려준다. 원본은
    `response_format="content_and_artifact"`라 2-튜플을 돌려주지만, 여기서는
    `ainvoke`로 content만 받아 문자열 하나로 통일한다 — 거부 시엔 사유 문자열을
    같은 자리에 돌려줘야 하기 때문이다.
    """
    remaining = budget

    async def gated(**kwargs: Any) -> Any:
        nonlocal remaining
        if remaining <= 0:
            return _BUDGET_MESSAGE
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


# ── ToolMessage → Fact ───────────────────────────────────────────────────


@dataclass
class ToolCall:
    name: str
    args: dict
    payload: dict | None
    raw: str


def message_text(message: Any) -> str:
    """`.text`는 langchain-core 1.x에서 메서드 → 프로퍼티로 바뀌었다.

    호환 기간이라 프로퍼티가 **호출도 되는** 문자열을 돌려준다 — `callable()`을 먼저
    보면 구형 경로로 빠져 deprecation 경고가 뜬다. 문자열 판정을 앞에 둔다.
    """
    text = getattr(message, "text", None)
    if isinstance(text, str):
        return text
    if callable(text):
        return str(text())
    return str(getattr(message, "content", ""))


def _parse_payload(content: Any) -> dict | None:
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        # MCP content 블록 리스트 — text 조각만 이어붙인다
        text = "".join(
            b.get("text", "") for b in content if isinstance(b, dict) and "text" in b
        )
        return _parse_payload(text) if text else None
    if not isinstance(content, str):
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def collect_tool_calls(messages: Sequence[BaseMessage]) -> list[ToolCall]:
    """`ToolMessage`를 `tool_call_id`로 원래 tool_call과 이어 붙인다."""
    args_by_id: dict[str, tuple[str, dict]] = {}
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            args_by_id[call["id"]] = (call["name"], call.get("args") or {})

    calls = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        name, args = args_by_id.get(message.tool_call_id, (message.name or "", {}))
        raw = message_text(message)
        calls.append(
            ToolCall(
                name=name, args=args, payload=_parse_payload(message.content), raw=raw
            )
        )
    return calls


# (fact_id, label, payload 키)
_NPM_FIELDS = (
    ("npm.latest_version", "최신 버전", "latest_version"),
    ("npm.last_release", "마지막 릴리스", "last_release"),
    ("npm.license", "라이선스", "license"),
    ("npm.deprecated", "deprecated", "deprecated"),
)
_PYPI_FIELDS = (
    ("pypi.latest_version", "최신 버전", "latest_version"),
    ("pypi.last_release", "마지막 릴리스", "last_release"),
    ("pypi.license", "라이선스", "license"),
    ("pypi.yanked", "yanked", "yanked"),
)
_GH_FIELDS = (
    ("gh.last_commit", "마지막 커밋", "last_commit_at"),
    ("gh.archived", "archived", "archived"),
    ("gh.contributors", "기여자 수", "contributors"),
    ("gh.stars", "스타", "stars"),
    ("gh.issue_close_rate", "이슈 처리율", "issue_resolution_rate"),
)


def _fields_to_facts(payload: dict, spec, url: str | None, now: str) -> list[Fact]:
    facts = []
    for fact_id, label, key in spec:
        value = payload.get(key)
        if value is None or value == "":
            continue
        facts.append(
            Fact(id=fact_id, label=label, value=str(value), url=url, retrieved_at=now)
        )
    return facts


def _web_facts(payload: dict, now: str) -> list[Fact]:
    facts = []
    for i, result in enumerate(payload.get("results") or [], start=1):
        if not isinstance(result, dict):
            continue
        title = (result.get("title") or "").strip()
        snippet = (result.get("snippet") or "").strip()
        facts.append(
            Fact(
                id=f"web.{i}",
                label=title[:80] or f"검색 결과 {i}",
                value=snippet or title or "(본문 없음)",
                url=result.get("url"),
                retrieved_at=now,
            )
        )
    return facts


def _registry_facts(call: ToolCall, now: str) -> list[Fact]:
    payload = call.payload or {}
    if call.name == "npm_package":
        name = payload.get("name") or call.args.get("name", "")
        return _fields_to_facts(
            payload, _NPM_FIELDS, f"https://www.npmjs.com/package/{name}", now
        )
    if call.name == "pypi_package":
        name = payload.get("name") or call.args.get("name", "")
        return _fields_to_facts(
            payload, _PYPI_FIELDS, f"https://pypi.org/project/{name}/", now
        )
    if call.name == "github_repo_health":
        full = (
            payload.get("full_name")
            or f"{call.args.get('owner')}/{call.args.get('repo')}"
        )
        return _fields_to_facts(payload, _GH_FIELDS, f"https://github.com/{full}", now)
    return []


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def call_matches(call: ToolCall, candidate_name: str) -> bool:
    """이 툴 호출이 이 후보에 대한 것인지 — 인자로만 판단한다 (LLM에 묻지 않는다)."""
    target = _norm(candidate_name)
    if not target:
        return False
    if call.name in ("npm_package", "pypi_package"):
        return _norm(str(call.args.get("name", ""))) == target
    if call.name == "github_repo_health":
        owner = _norm(str(call.args.get("owner", "")))
        repo = _norm(str(call.args.get("repo", "")))
        return target in (repo, f"{owner}{repo}")
    if call.name == "web_search":
        return target in _norm(str(call.args.get("query", "")))
    return False


def facts_for_candidate(calls: Sequence[ToolCall], name: str, now: str) -> list[Fact]:
    keyed: dict[str, Fact] = {}
    web: list[Fact] = []
    for call in calls:
        if call.payload is None or not call_matches(call, name):
            continue
        if call.name == "web_search":
            web.extend(_web_facts(call.payload, now))
        else:
            for fact in _registry_facts(call, now):
                keyed[fact.id] = fact

    facts = list(keyed.values())
    seen: set[str | None] = set()
    rank = 0
    for fact in web:
        if fact.url in seen:
            continue
        seen.add(fact.url)
        rank += 1
        if rank > _MAX_WEB_FACTS:
            break
        facts.append(fact.model_copy(update={"id": f"web.{rank}"}))
    return facts


# ── 조사 ─────────────────────────────────────────────────────────────────


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}… (생략)"


def build_transcript(calls: Sequence[ToolCall], messages: Sequence[BaseMessage]) -> str:
    """에이전트 히스토리를 평문으로 접는다.

    원본 메시지를 그대로 다음 프롬프트에 넣으면 tool_use/tool_result 쌍이 새 toolConfig와
    맞지 않아 Bedrock이 거부할 수 있다. 평문이면 그 문제가 없고 토큰도 준다.
    """
    lines = []
    for call in calls:
        lines.append(f"[{call.name}] {json.dumps(call.args, ensure_ascii=False)}")
        lines.append(_truncate(call.raw, _TOOL_PAYLOAD_CHARS))
    final = [
        m for m in messages if isinstance(m, AIMessage) and message_text(m).strip()
    ]
    if final:
        lines.append(f"[에이전트 요약] {message_text(final[-1]).strip()}")
    return "\n".join(lines) or "(툴 호출 없음)"


async def _call_tool(
    tools: dict[str, BaseTool], name: str, args: dict
) -> tuple[dict | None, str | None]:
    """조회 실패를 예외로 올리지 않는다 — gaps로 격하한다 (불변식 11)."""
    tool = tools.get(name)
    if tool is None:
        return None, f"{name} 툴 없음"
    try:
        return _parse_payload(await tool.ainvoke(args)), None
    except Exception as e:  # noqa: BLE001 — 어떤 실패든 gaps로 내려간다
        return None, f"{name} 조회 실패: {e}"


async def topup_dossier(
    draft_name: str,
    kind: str,
    facts: list[Fact],
    tools: dict[str, BaseTool],
    now: str,
) -> tuple[list[Fact], list[str]]:
    """kind별 필수 사실이 비었으면 코드가 결정론적으로 채운다.

    에이전트가 자유롭게 탐색한 결과만 쓰면 후보마다 사실 커버리지가 달라져
    `evaluate`의 maturity·risk가 서로 다른 근거 위에서 계산된다.
    """
    extra: list[Fact] = []
    gaps: list[str] = []
    ids = {f.id for f in facts}

    def has(prefix: str) -> bool:
        return any(i.startswith(prefix) for i in ids | {f.id for f in extra})

    if kind == "library" and not (has("npm.") or has("pypi.")):
        for tool_name in ("npm_package", "pypi_package"):
            payload, error = await _call_tool(tools, tool_name, {"name": draft_name})
            if payload:
                call = ToolCall(tool_name, {"name": draft_name}, payload, "")
                extra.extend(_registry_facts(call, now))
                break
            if error:
                gaps.append(error)
        if not has("npm.") and not has("pypi."):
            gaps.append(f"레지스트리에서 '{draft_name}'을 찾지 못함")

    if kind in ("library", "software") and not has("gh."):
        gaps.append("GitHub 저장소 미확인 — owner/repo를 특정하지 못함")

    if kind == "method":
        gaps.append("레지스트리 없음 (method)")
        if not has("web."):
            gaps.append("웹검색 근거 없음 — 승인 거부 또는 미검색")

    return extra, gaps


async def _search_component(
    component: Component,
    interview: Interview,
    llm: ChatBedrockConverse,
    tools: dict[str, BaseTool],
    gate: SearchGate,
    max_candidates: int,
) -> list[Candidate]:
    now = datetime.now(UTC).isoformat()
    # 웹검색 예산은 요소마다 따로 준다 — 한 요소가 전체 예산을 다 먹으면 안 된다.
    if "web_search" in tools:
        tools = {**tools, "web_search": wrap_web_search(tools["web_search"], gate)}

    # checkpointer=False — 안 주면 바깥 그래프의 SqliteSaver(동기 전용)를 물려받는데
    # 이 에이전트는 ainvoke로 돈다 ("SqliteSaver does not support async methods").
    agent = create_agent(
        llm,
        list(tools.values()),
        system_prompt=SEARCH_AGENT_SYSTEM_PROMPT,
        checkpointer=False,
    )
    task = SEARCH_AGENT_TASK_PROMPT.format(
        component_name=component.name,
        component_kind=component.kind,
        component_why=component.why,
        approach_notes=component.approach_notes,
        search_hints=", ".join(component.search_hints) or "(없음)",
        refined_brief=interview.refined_brief,
    )

    # recursion_limit을 반드시 넘긴다 — create_agent는 그래프에 9999를 바인딩해둔다.
    # 안 넘기면 툴 루프가 사실상 무제한으로 돈다.
    result = await agent.ainvoke(
        {"messages": [HumanMessage(task)]},
        config={"recursion_limit": _RECURSION_LIMIT},
    )
    messages = result["messages"]
    calls = collect_tool_calls(messages)

    parsed, raw = invoke_structured(
        SEARCH_EXTRACT_PROMPT,
        llm.with_structured_output(CandidateList, include_raw=True),
        {
            "transcript": build_transcript(calls, messages),
            "max_candidates": max_candidates,
        },
        SEARCH_EXTRACT_RETRY_HINT,
    )
    if parsed is None:
        raise RuntimeError(f"CandidateList 구조화 출력 파싱 실패: {raw}")

    candidates = []
    for draft in parsed.candidates[:max_candidates]:
        facts = facts_for_candidate(calls, draft.name, now)
        extra, gaps = await topup_dossier(draft.name, draft.kind, facts, tools, now)
        candidates.append(
            Candidate(
                component=component.name,
                name=draft.name,
                kind=draft.kind,
                what_it_is=draft.what_it_is,
                dossier=[*facts, *extra],
                dossier_gaps=gaps,
            )
        )
    return candidates


async def _run_search(
    components: Sequence[Component],
    interview: Interview,
    llm: ChatBedrockConverse,
    gate: SearchGate,
    max_candidates: int,
    concurrency: int,
) -> tuple[list[Candidate], list[str]]:
    tools_list = await make_mcp_client().get_tools()
    tools = {t.name: t for t in tools_list}

    semaphore = asyncio.Semaphore(concurrency)
    gaps: list[str] = []

    async def one(component: Component) -> list[Candidate]:
        async with semaphore:
            return await _search_component(
                component, interview, llm, tools, gate, max_candidates
            )

    results = await asyncio.gather(
        *(one(c) for c in components), return_exceptions=True
    )

    candidates: list[Candidate] = []
    for component, result in zip(components, results, strict=True):
        if isinstance(result, BaseException):
            # 요소 하나가 죽어도 나머지는 계속 간다 (불변식 11)
            gaps.append(f"'{component.name}' 조사 실패: {result}")
            continue
        candidates.extend(result)
    return candidates, gaps


def search_node(
    state: ScoutState,
    *,
    llm: ChatBedrockConverse,
    approve: Approve = default_approve,
) -> dict:
    from scout.config import Settings

    slug = state["slug"]
    components = state.get("components") or []
    if not components:
        store.add_gap(slug, "search", "통과한 요소가 없어 조사를 건너뜀")
        return {"candidates": []}

    settings = Settings()
    gate = SearchGate(approve=approve)
    candidates, gaps = asyncio.run(
        _run_search(
            components,
            state["interview"],
            llm,
            gate,
            state.get("max_candidates", settings.scout_max_candidates),
            settings.scout_mcp_concurrency,
        )
    )

    for candidate in candidates:
        store.upsert_candidate(slug, candidate)
    for note in [*gaps, *gate.notes]:
        store.add_gap(slug, "search", note)
    if not candidates:
        store.add_gap(slug, "search", "후보를 하나도 찾지 못함")

    return {"candidates": candidates}
