"""search 단계 — ReAct 에이전트가 툴을 골라 후보를 찾고 dossier를 모은다.

요소마다 `langchain.agents.create_agent` 하나를 돌린다 (001/stages/2-search.md). 에이전트는
**어떤 툴을 부를지만** 정한다 — `Fact.value`는 에이전트가 쓴 문장이 아니라
`ToolMessage`의 원본 payload에서 코드가 뽑는다. 이 경계가 무너지면 judge가 인용하는
dossier 자체가 LLM 생성물이 되어 불변식 4가 지탱하던 "judge는 사실을 지어낼 수 없다"가
뿌리에서 깨진다.

`web_search`는 사람 승인을 거친다 — 거부되면 원본 툴을 호출하지 않으므로 egress가
일어나지 않고, 거부 사유가 툴 결과로 에이전트에 돌아가 질의를 고쳐 재시도한다.
게이트 구현은 `scout/approval.py`, 에이전트 기록 파싱은 `scout/agentkit.py`에 있다
— `design`과 공유한다.
LangGraph `interrupt()`를 쓰지 않는 이유는 2-search.md "왜 interrupt()가 아닌가" 참고 —
승인 콜러블이 나중에 `interrupt()`로 갈아끼울 이음매다.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from scout import store
from scout.agentkit import ToolCall, build_transcript, collect_tool_calls, parse_payload
from scout.approval import SearchGate, default_approve, wrap_web_search
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
    from collections.abc import Sequence

    from langchain_aws import ChatBedrockConverse
    from langchain_core.tools import BaseTool

    from scout.approval import Approve
    from scout.schemas import Component, Interview
    from scout.state import ScoutState

_MAX_WEB_FACTS = 6
_RECURSION_LIMIT = 40


# ── ToolMessage → Fact ───────────────────────────────────────────────────

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


async def _call_tool(
    tools: dict[str, BaseTool], name: str, args: dict
) -> tuple[dict | None, str | None]:
    """조회 실패를 예외로 올리지 않는다 — gaps로 격하한다 (불변식 11)."""
    tool = tools.get(name)
    if tool is None:
        return None, f"{name} 툴 없음"
    try:
        return parse_payload(await tool.ainvoke(args)), None
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
        role_in_design=component.role_in_design,
        decision_question=component.decision_question,
        constraints="\n".join(f"- {c}" for c in component.constraints) or "- (없음)",
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
