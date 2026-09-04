"""`design`의 툴 결과가 dossier를 오염시키지 않는지 검사한다 — 네트워크를 쓰지 않는다.

검증하는 주장: **dossier는 `search`만 만든다** (불변식 15). `design`도 에이전트로
툴을 부르게 되면서 생긴 새 위험이다 — 설계 중에 스쳐본 값을 `facts`에 섞으면 kind
라우팅·top-up을 거치지 않은 사실이 judge의 인용 대상이 되어, **grounding은 통과하는데
후보마다 근거 커버리지가 달라진다.** 불변식 4·13이 서 있는 자리가 무너진다.

`test_search_approval` 7번과 **같은 성격의 경계를 반대편에서** 지킨다 — 저쪽은
"사실은 툴 원본에서만 나온다", 이쪽은 "그 원본이라도 `design`에서는 사실이 아니다".

여기서 LLM 대역과 에이전트 대역을 쓰는 이유는, **툴을 실제로 부른 실행**에서 facts가
비어 있음을 봐야 하기 때문이다. 툴을 안 부르면 이 테스트는 아무것도 증명하지 않는다.

3번(`search_hints`)은 다른 둘과 성격이 다르다 — 경계가 아니라 **이 단계를 만든 이유**를
지킨다. 힌트가 비어도 파이프라인은 돌기 때문에(그게 `analyze` 시절의 상태였다) 조용히
원래대로 돌아가는 걸 막을 장치가 필요하다.
"""

import sqlite3
from pathlib import Path
from typing import ClassVar

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableLambda
from scout import store
from scout.schemas import Architecture, Component, Design, Fact, Interview
from scout.stages import design as design_stage

SLUG = "design-no-facts"

# design 에이전트가 툴에서 실제로 본 값. 이 문자열이 DB에 나타나면 경계가 깨진 것이다.
SEEN_VERSION = "4.8.1"
NPM_PAYLOAD = (
    '{"name": "socket.io", "latest_version": "' + SEEN_VERSION + '", '
    '"last_release": "2026-08-20", "license": "MIT", "weekly_downloads": 7000000}'
)


@pytest.fixture
def runs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """`design_node`는 `runs_dir`을 받지 않고 `Settings()`로 푼다 — 환경으로 돌린다."""
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("SCOUT_RUNS_DIR", str(tmp_path))
    return str(tmp_path)


# ── 대역 ─────────────────────────────────────────────────────────────────


class _SpyTool:
    """MCP 툴 대역. `search`가 dossier를 만들 때와 **같은 payload**를 돌려준다."""

    name = "npm_package"
    description = "npm 패키지 메타데이터"
    args_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    metadata = None

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def ainvoke(self, args: dict) -> str:
        self.calls.append(args)
        return NPM_PAYLOAD


class _FakeMCPClient:
    def __init__(self, tools: list) -> None:
        self._tools = tools

    async def get_tools(self) -> list:
        return self._tools


class _FakeAgent:
    """설계 에이전트 대역 — **실제로 툴을 부르고** 그 원본을 ToolMessage로 남긴다."""

    def __init__(self, tools: list) -> None:
        self.tools = {t.name: t for t in tools}

    async def astream(self, inputs, config=None, stream_mode=None):
        raw = await self.tools["npm_package"].ainvoke({"name": "socket.io"})
        yield {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "npm_package",
                            "args": {"name": "socket.io"},
                            "type": "tool_call",
                        }
                    ],
                ),
                ToolMessage(content=raw, tool_call_id="c1", name="npm_package"),
                AIMessage(content="socket.io가 실무에서 쓰이는 이름임을 확인했다"),
            ]
        }


def _design_fixture(*, search_hints: list[str] | None = None) -> Design:
    return Design(
        architecture=Architecture(
            summary="단일 Node 백엔드가 실시간 연결과 REST를 함께 처리한다.",
            shape="브라우저 → Node → PostgreSQL",
            data_flow="전송 → DB 기록 → 룸 브로드캐스트",
            build_order=["메시지 스키마", "실시간 전달"],
        ),
        components=[
            Component(
                name="실시간 메시지 전달",
                kind="feature",
                role_in_design="사용자 간 즉시 전달이 서비스의 핵심",
                decision_question="즉시 전달을 감당할 전달 계층은 무엇인가",
                alternatives=["Server-Sent Events", "WebSocket"],
                necessity="essential",
                necessity_reason="없으면 서비스가 성립하지 않는다",
                priority=1,
                approach_notes="WebSocket 기반",
                search_hints=(
                    ["websocket server node"] if search_hints is None else search_hints
                ),
            )
        ],
    )


class _StubLLM:
    """설계 추출 LLM 대역. 프롬프트를 기록해 **툴 값이 설계에 전달됐는지**를 본다."""

    def __init__(self, design: Design) -> None:
        self.design = design
        self.prompts: list[str] = []

    def with_structured_output(self, _model, include_raw: bool = False):
        def _run(messages):
            self.prompts.append(str(messages))
            return {"parsed": self.design, "raw": None}

        return RunnableLambda(_run)


def _interview() -> Interview:
    return Interview(
        raw_description="사내 200명 팀 채팅 앱",
        refined_brief="3인 TypeScript 팀이 3개월 안에 만드는 사내 200명 팀 채팅 앱",
        assumptions=["동시 접속 100명 규모"],
    )


def _run_design_node(
    runs_dir: str, monkeypatch: pytest.MonkeyPatch, design: Design
) -> tuple[dict, _SpyTool, _StubLLM]:
    spy = _SpyTool()
    # make_mcp_client는 stdio 세션 타임아웃을 인자로 받는다 — 대역도 받아야 한다
    monkeypatch.setattr(
        design_stage, "make_mcp_client", lambda *_args: _FakeMCPClient([spy])
    )
    monkeypatch.setattr(
        design_stage, "create_agent", lambda llm, tools, **kwargs: _FakeAgent(tools)
    )
    llm = _StubLLM(design)
    result = design_stage.design_node(
        {"slug": SLUG, "interview": _interview(), "max_components": 3}, llm=llm
    )
    return result, spy, llm


# ── 조회 도구 ────────────────────────────────────────────────────────────


def _table_dump(runs_dir: str, table: str) -> list[tuple]:
    conn = sqlite3.connect(Path(runs_dir) / SLUG / "scout.db")
    try:
        return conn.execute(f"SELECT * FROM {table} WHERE slug = ?", (SLUG,)).fetchall()
    finally:
        conn.close()


def _notes(runs_dir: str) -> list[str]:
    return [g["note"] for g in store.get_all_gaps(SLUG, runs_dir=runs_dir)]


# ── 1 · 툴을 불러도 facts에 행이 생기지 않는다 ───────────────────────────


def test_design_calls_a_tool_but_writes_no_facts(
    runs_dir: str, monkeypatch: pytest.MonkeyPatch
):
    """★ 툴 호출이 **실제로 일어난** 실행에서 facts가 비어 있어야 한다.

    툴을 안 불렀으면 이 테스트는 아무것도 증명하지 않으므로, 호출됐다는 것을 먼저 본다.
    """
    result, spy, _ = _run_design_node(runs_dir, monkeypatch, _design_fixture())

    assert spy.calls == [{"name": "socket.io"}], "설계 에이전트가 툴을 부르지 않았다"
    assert result["architecture"].shape  # 설계는 정상적으로 나왔다
    assert _table_dump(runs_dir, "facts") == [], (
        "design이 facts에 썼다 — 라우팅·top-up을 안 거친 사실이 dossier에 섞인다"
    )
    assert _table_dump(runs_dir, "candidates") == [], "dossier는 search만 만든다"


# ── 2 · design이 본 값이 candidates/facts 어디에도 없다 ──────────────────


def test_the_value_design_saw_reaches_the_design_not_the_dossier(
    runs_dir: str, monkeypatch: pytest.MonkeyPatch
):
    """★ 같은 payload가 **설계에는 전달되고 dossier에는 안 들어간다.**

    "facts가 비었다"만 보면 툴 값이 애초에 어디에도 안 갔을 수도 있다. 값이 설계
    프롬프트까지는 갔다는 것을 함께 봐야 경계가 지켜졌다는 뜻이 된다.
    """
    _, _, llm = _run_design_node(runs_dir, monkeypatch, _design_fixture())

    assert SEEN_VERSION in llm.prompts[0], (
        "툴 원본이 설계 추출 프롬프트에 안 들어갔다 — 툴을 부르는 의미가 없다"
    )
    for table in ("facts", "candidates"):
        dumped = str(_table_dump(runs_dir, table))
        assert SEEN_VERSION not in dumped, f"{table}에 설계 단계의 툴 값이 남았다"
        assert "socket.io" not in dumped, f"{table}에 설계 단계의 후보명이 남았다"


def test_design_does_not_touch_a_dossier_search_already_built(
    runs_dir: str, monkeypatch: pytest.MonkeyPatch
):
    """`search`가 만든 사실은 그대로 두고, 거기에 자기 값을 얹지도 않는다.

    `clear_stage_output(slug, "design")`이 facts를 비우지 않는다는 뜻이기도 하다 —
    `design`의 산출물이 아니므로 지울 것도 없고 더할 것도 없다.
    """
    searched = Fact(
        id="npm.last_release",
        label="마지막 릴리스",
        value="2026-06-01",
        url=None,
        retrieved_at="2026-09-03T00:00:00Z",
    )
    store.upsert_facts(SLUG, "socket.io", [searched], runs_dir=runs_dir)

    _run_design_node(runs_dir, monkeypatch, _design_fixture())

    rows = store.get_facts(SLUG, "socket.io", runs_dir=runs_dir)
    assert [f.value for f in rows] == ["2026-06-01"], (
        "design이 dossier를 지우거나 자기 값을 얹었다"
    )


# ── 3 · 통과 결정 지점의 search_hints가 비면 gaps에 남는다 ───────────────


def test_empty_search_hints_are_recorded_as_a_gap(
    runs_dir: str, monkeypatch: pytest.MonkeyPatch
):
    """★ 힌트가 비면 `search`가 한국어 추상어로 `npm_search`를 부른다 (불변식 16).

    파이프라인은 그래도 돌기 때문에 기록이 없으면 조용히 회귀한다.
    """
    _run_design_node(runs_dir, monkeypatch, _design_fixture(search_hints=[]))

    assert any("search_hints가 비어" in n for n in _notes(runs_dir))


def test_filled_search_hints_leave_no_gap(
    runs_dir: str, monkeypatch: pytest.MonkeyPatch
):
    """반대 방향 — 힌트가 있으면 경고가 없어야 한다. 늘 뜨면 기록이 무시된다."""
    _run_design_node(runs_dir, monkeypatch, _design_fixture())

    assert not any("search_hints" in n for n in _notes(runs_dir))
