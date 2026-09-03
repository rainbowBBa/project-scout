"""결정 지점의 입도를 검사한다 — LLM도 네트워크도 쓰지 않는다.

검증하는 주장: **고를 보기가 없는 결정 지점은 조사로 넘어가지 않고, 조용히 사라지지도
않는다.**

실측에서 세 형태로 깨졌다 (CHANGELOG v26) — "어떻게 구성할 것인가"처럼 선택이 아닌
질문이 통과해 억지 후보가 1위로 올라왔고, 브리프가 지정한 `lang chain`이 자기 비교에서
1위가 됐고, `"SSE vs WebSocket"`을 물어놓고 SSE도 WebSocket도 후보에 없었다.

프롬프트 반례만으로는 못 막는다 — 지시 준수가 약한 모델에서도 유지돼야 하므로 코드가
강제한다. 그 배선을 여기서 고정한다.
"""

from pathlib import Path

import pytest
from scout import store
from scout.schemas import Candidate, Component, Fact
from scout.stages.design import close_undecidable, select_passing_components
from scout.stages.report import build_report_context
from scout.stages.search import uncovered_alternatives

SLUG = "decision-points"


@pytest.fixture
def runs_dir(tmp_path: Path) -> str:
    return str(tmp_path)


def _component(
    name: str,
    *,
    alternatives: list[str],
    question: str = "무엇으로 할 것인가",
) -> Component:
    return Component(
        name=name,
        kind="feature",
        role_in_design="역할",
        decision_question=question,
        alternatives=alternatives,
        necessity="essential",
        necessity_reason="200명 규모에서 핵심",
        priority=1,
        approach_notes="",
        search_hints=["hint"],
    )


def test_one_alternative_does_not_pass_to_search():
    """★ 고를 보기가 하나면 결정 지점이 아니다 — 실측에서 억지 후보가 1위로 올라왔다."""
    components = [
        _component("스트리밍", alternatives=["SSE", "WebSocket"]),
        _component("에이전트 라이브러리", alternatives=["LangChain"]),
        _component("에러 처리", alternatives=[]),
    ]

    passing = select_passing_components(components, 10)

    assert [c.name for c in passing] == ["스트리밍"], (
        "보기가 2개 미만인 결정 지점이 통과했다 — search가 억지 후보를 만든다"
    )


def test_code_closes_the_decision_and_writes_why():
    """프롬프트가 needs_comparison=true로 줘도 코드가 내린다 (불변식 18)."""
    brief_specified = _component("에이전트 라이브러리", alternatives=["LangChain"])
    not_a_choice = _component("에러 처리", alternatives=[], question="어느 수준으로 구현할 것인가")
    real = _component("스트리밍", alternatives=["SSE", "WebSocket"])

    closed = close_undecidable([brief_specified, not_a_choice, real])

    assert [c.name for c in closed] == ["에이전트 라이브러리", "에러 처리"]
    assert brief_specified.needs_comparison is False
    assert "LangChain" in brief_specified.no_comparison_reason, (
        "브리프가 지정한 기술이 무엇인지 이유에 남아야 한다"
    )
    assert not_a_choice.no_comparison_reason, "이유 없이 내리면 보고서가 설명하지 못한다"
    # 진짜 결정 지점은 건드리지 않는다 — 필터가 과하게 막으면 조사할 게 없어진다
    assert real.needs_comparison is True
    assert real.no_comparison_reason == ""


def test_closing_is_idempotent():
    """재실행·`--from`으로 두 번 돌아도 이유가 겹쳐 쓰이지 않는다."""
    component = _component("배포", alternatives=["ECS"])

    close_undecidable([component])
    first = component.no_comparison_reason
    assert close_undecidable([component]) == [], "이미 닫힌 것을 다시 내렸다"
    assert component.no_comparison_reason == first


def test_closed_decision_appears_in_the_report(runs_dir: str):
    """★ 조용히 사라지지 않는다 — 보고서에 이유와 함께 실린다 (불변식 12).

    필터가 늘면 버려지는 요소가 생기는데, 그게 보고서에 안 보이면 사용자는 설계가
    무엇을 전제로 깔았는지 알 수 없다.
    """
    components = [_component("에이전트 라이브러리", alternatives=["LangChain"])]
    close_undecidable(components)
    store.upsert_components(SLUG, components, runs_dir=runs_dir)

    ctx = build_report_context(SLUG, runs_dir=runs_dir)

    closed = ctx["closed"]
    assert [c.name for c in closed] == ["에이전트 라이브러리"]
    assert "LangChain" in closed[0].no_comparison_reason
    # "필요 없어서 뺀 것"과 섞이면 설계의 전제가 보이지 않는다 (불변식 17)
    assert ctx["deferred"] == []


def test_alternatives_survive_the_store_roundtrip(runs_dir: str):
    """`--from search`는 DB에서 결정 지점을 다시 읽는다 — 여기서 사라지면 필터가 무력해진다."""
    component = _component("스트리밍", alternatives=["Server-Sent Events", "WebSocket"])
    store.upsert_components(SLUG, [component], runs_dir=runs_dir)

    loaded = store.get_components(SLUG, runs_dir=runs_dir)

    assert loaded[0].alternatives == ["Server-Sent Events", "WebSocket"]
    assert select_passing_components(loaded, 10), "왕복 후에 통과 필터가 막았다"


def _candidate(name: str, what_it_is: str = "설명") -> Candidate:
    return Candidate(
        component="스트리밍",
        name=name,
        kind="library",
        what_it_is=what_it_is,
        dossier=[
            Fact(
                id="npm.license",
                label="라이선스",
                value="MIT",
                url=None,
                retrieved_at="2026-09-03T00:00:00Z",
            )
        ],
    )


def test_uncovered_alternative_is_recorded():
    """★ 실측된 실패 — "Next.js vs Vite+React"인데 Next.js가 후보에 없었고 아무 기록도 없었다."""
    component = _component("프론트엔드", alternatives=["Next.js", "Vite + React"])

    notes = uncovered_alternatives(component, [_candidate("vite")])

    assert len(notes) == 1, f"미커버 보기가 정확히 하나여야 한다: {notes}"
    assert "Next.js" in notes[0]


def test_covered_alternative_is_not_reported():
    """느슨하게 맞춘다 — 보기가 패턴명이고 후보가 그 구현 패키지면 커버된 것이다."""
    component = _component("스트리밍", alternatives=["Server-Sent Events", "WebSocket"])
    found = [
        _candidate("sse-starlette", "Starlette용 Server-Sent Events 응답"),
        _candidate("websockets", "WebSocket 서버·클라이언트"),
    ]

    assert uncovered_alternatives(component, found) == []
