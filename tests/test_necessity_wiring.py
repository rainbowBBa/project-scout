"""걸러낸 결정 지점이 실제로 걸러지는지 검사한다 — LLM도 네트워크도 쓰지 않는다.

검증하는 주장: **`design`이 걸러낸 것은 `search`에 들어가지 않고, 보고서에서는
사라지지 않는다.** 이 도구의 차별점은 둘인데(grounding · `necessity`) 앞의 것만
테스트가 있으면 증거가 비대칭이다 (07-검증.md).

걸러놓고 `search`가 그냥 다 조사하면 "최소 1개 걸러짐"은 통과하지만 기능은 아무
효과가 없다. 반대로 걸러진 것이 보고서에서 지워지면 사용자는 설계가 무엇을 전제로
깔았는지 알 수 없다 (불변식 12). 그 두 경우를 여기서 잡는다.

★ 통과 필터는 **축이 셋**이다 — `necessity`("필요한가") · `needs_comparison`("지금
비교해서 골라야 하는가") · `alternatives`("고를 것이 있는가"). 앞의 둘이 다른 축인
이유는 불변식 17, 셋째는 불변식 18에 있다. 세 축이 각각 살아 있는지를 본다
(셋째의 세부는 `test_decision_points`가 더 깊게 본다).

`test_search_approval`·`test_grounding`과 같은 성격이다 — 판단의 품질이 아니라 배선을 본다.
"""

from pathlib import Path

import pytest
from scout import store
from scout.schemas import Architecture, Component, Design
from scout.stages.design import _record_gaps, select_passing_components
from scout.stages.report import build_report_context, render_report
from scout.stages.search import search_node

SLUG = "necessity-wiring"


@pytest.fixture
def runs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """store 기본 경로를 tmp로 돌린다.

    `search_node`와 `_record_gaps`는 `runs_dir`을 받지 않고 `Settings()`로 푼다 —
    그래서 인자가 아니라 환경으로 돌린다. `AWS_DEFAULT_REGION`은 `Settings`의 필수
    필드라 값이 있어야 생성된다 (크레덴셜이 아니다 — 불변식 9).
    """
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("SCOUT_RUNS_DIR", str(tmp_path))
    return str(tmp_path)


def _component(
    name: str,
    *,
    necessity: str = "essential",
    needs_comparison: bool = True,
    alternatives: list[str] | None = None,
    no_comparison_reason: str = "",
    priority: int = 1,
) -> Component:
    return Component(
        name=name,
        kind="feature",
        role_in_design=f"{name}은 설계에서 이 역할을 한다",
        decision_question=f"{name}을 무엇으로 할 것인가",
        alternatives=["SSE", "WebSocket"] if alternatives is None else alternatives,
        needs_comparison=needs_comparison,
        no_comparison_reason=no_comparison_reason,
        necessity=necessity,
        necessity_reason=f"200명 규모 · 3인 팀 기준 {necessity}",
        priority=priority,
        approach_notes="",
        search_hints=["websocket server node"],
    )


def _all_four() -> list[Component]:
    """네 갈래를 한 번에 만든다 — 통과 / 필요없음 / 이미정해짐 / 고를것없음."""
    return [
        _component("실시간 메시지 전달", priority=1),
        _component("메시지 전문검색", necessity="defer", priority=5),
        _component(
            "인증",
            needs_comparison=False,
            no_comparison_reason="사내 SSO가 이미 있어 그것을 쓴다",
            priority=2,
        ),
        _component("에이전트 라이브러리", alternatives=["LangChain"], priority=3),
    ]


# ── 축 1·2·3 — 걸러진 것은 search 입력에 들어가지 않는다 ─────────────────


def test_deferred_components_do_not_reach_search():
    """축 1 — `necessity`가 defer/unnecessary면 조사하지 않는다."""
    components = [
        _component("실시간 메시지 전달"),
        _component("메시지 전문검색", necessity="defer"),
        _component("음성 통화", necessity="unnecessary"),
    ]

    passing = select_passing_components(components, 10)

    assert [c.name for c in passing] == ["실시간 메시지 전달"], (
        "걸러낸 요소가 search 입력에 남았다 — necessity가 장식이 된다"
    )


def test_closed_decisions_do_not_reach_search():
    """축 2 — 이미 정해진 결정은 필요하더라도 조사하지 않는다 (불변식 17)."""
    components = [
        _component("실시간 메시지 전달"),
        _component("인증", needs_comparison=False, no_comparison_reason="사내 SSO"),
    ]

    passing = select_passing_components(components, 10)

    assert [c.name for c in passing] == ["실시간 메시지 전달"]


def test_thin_alternatives_do_not_reach_search():
    """축 3 — 고를 보기가 없으면 결정 지점이 아니다 (불변식 18).

    세부는 `test_decision_points`가 본다. 여기서는 **통과 필터의 축으로 살아 있는지**만
    확인한다 — 축이 조용히 빠지면 억지 후보가 다시 1위로 올라온다.
    """
    components = [
        _component("실시간 메시지 전달"),
        _component("에이전트 라이브러리", alternatives=["LangChain"]),
        _component("에러 처리", alternatives=[]),
    ]

    passing = select_passing_components(components, 10)

    assert [c.name for c in passing] == ["실시간 메시지 전달"]


def test_three_axes_are_independent():
    """세 축이 각각 혼자서도 막는다 — 하나가 죽어도 다른 축에 가려 안 보일 수 있다."""
    passing = select_passing_components(_all_four(), 10)

    assert [c.name for c in passing] == ["실시간 메시지 전달"]


def test_priority_cut_is_the_last_filter_not_the_first():
    """규모 조절은 **통과한 것 중에서** 자른다 — 걸러내기와 순서가 바뀌면 안 된다.

    반대 순서면 priority가 앞선 defer 요소가 자리를 차지해 통과 요소가 밀려난다.
    """
    components = [
        _component("인증", needs_comparison=False, priority=1),
        _component("메시지 전문검색", necessity="defer", priority=2),
        _component("실시간 메시지 전달", priority=3),
        _component("파일 첨부", necessity="valuable", priority=4),
    ]

    passing = select_passing_components(components, 1)

    assert [c.name for c in passing] == ["실시간 메시지 전달"], (
        "priority 컷이 걸러내기보다 먼저 걸렸다"
    )


def test_filtered_components_still_persist_for_the_report(runs_dir: str):
    """걸러진 것도 `components` 테이블에는 전부 남는다 — 여기서 잘리면 보고서가 못 쓴다.

    `select_passing_components`가 자르는 것은 **상태로 넘기는 부분집합**일 뿐이다.
    """
    store.upsert_components(SLUG, _all_four(), runs_dir=runs_dir)

    stored = store.get_components(SLUG, runs_dir=runs_dir)

    assert len(stored) == 4
    assert len(select_passing_components(stored, 10)) == 1


# ── search가 실제로 그 목록만 본다 ───────────────────────────────────────


def test_search_skips_entirely_when_nothing_passes(runs_dir: str):
    """★ 소비자 쪽 배선 — `search`는 `state["components"]`만 본다.

    통과 목록이 비면 MCP도 LLM도 부르지 않고 나온다. 여기서 DB의 전체 요소를 다시
    읽으면 걸러내기가 예산을 하나도 아끼지 못한다.
    """
    store.upsert_components(SLUG, _all_four(), runs_dir=runs_dir)

    result = search_node({"slug": SLUG, "components": []}, llm=None)

    assert result == {"candidates": []}
    assert any(
        "건너뜀" in g["note"] for g in store.get_all_gaps(SLUG, runs_dir=runs_dir)
    )


# ── 걸러진 것은 보고서에서 사라지지 않는다 (불변식 12) ───────────────────


def _rendered_sections(runs_dir: str) -> tuple[str, str, str]:
    """보고서를 세 섹션으로 잘라 돌려준다 — 어느 섹션에 실렸는지가 검사 대상이다."""
    html = render_report(build_report_context(SLUG, runs_dir=runs_dir))
    closed_at = html.index("이미 정해진 부분")
    deferred_at = html.index("지금 만들지 않아도 되는 것")
    skipped_at = html.index("이번에 다루지 않은 요소")
    return html[closed_at:deferred_at], html[deferred_at:skipped_at], html[skipped_at:]


def test_deferred_and_closed_land_in_different_sections(runs_dir: str):
    """★ "필요 없어서"와 "이미 정해져서"는 다른 섹션이다 (불변식 17).

    합치면 사용자가 설계의 전제를 못 본다 — 안 만들어도 되는 것과, 만들지만 이미
    정해둔 것은 다음 행동이 다르다.
    """
    store.upsert_components(SLUG, _all_four(), runs_dir=runs_dir)

    closed, deferred, _ = _rendered_sections(runs_dir)

    assert "인증" in closed and "사내 SSO가 이미 있어" in closed
    assert "메시지 전문검색" in deferred and "defer" in deferred
    assert "인증" not in deferred, "이미 정해진 것이 '필요 없는 것'으로 뭉개졌다"
    assert "메시지 전문검색" not in closed


def test_code_closed_decision_appears_with_its_reason(runs_dir: str):
    """코드가 내린 결정도 이유와 함께 실린다 — 조용히 사라지면 필터가 늘 때 위험하다."""
    components = _all_four()
    thin = next(c for c in components if c.name == "에이전트 라이브러리")
    thin.needs_comparison = False
    thin.no_comparison_reason = (
        "설계에서 이미 정해졌다 — LangChain뿐이라 비교할 대안이 없다"
    )
    store.upsert_components(SLUG, components, runs_dir=runs_dir)

    closed, _, _ = _rendered_sections(runs_dir)

    assert "에이전트 라이브러리" in closed
    assert "LangChain뿐이라 비교할 대안이 없다" in closed


def test_priority_cut_lands_in_its_own_section(runs_dir: str):
    """규모 컷에 밀린 것은 "다루지 않은 요소"다 — 걸러낸 것과 이유가 다르다."""
    components = [
        _component("실시간 메시지 전달", priority=1),
        _component("파일 첨부", necessity="valuable", priority=4),
    ]
    store.upsert_components(SLUG, components, runs_dir=runs_dir)

    _, deferred, skipped = _rendered_sections(runs_dir)

    assert "파일 첨부" in skipped
    assert "--max-components" in skipped, "다시 돌리는 방법이 안 보인다"
    assert "파일 첨부" not in deferred


def test_empty_filter_sections_say_so_instead_of_disappearing(runs_dir: str):
    """전부 통과했으면 섹션을 지우지 않고 "해당 없음 + 이유"를 쓴다 (불변식 12)."""
    store.upsert_components(SLUG, [_component("실시간 메시지 전달")], runs_dir=runs_dir)

    closed, deferred, _ = _rendered_sections(runs_dir)

    assert "해당 없음" in closed
    assert "해당 없음" in deferred


# ── 걸러진 것이 0개면 경고가 남는다 ─────────────────────────────────────


def _design(components: list[Component]) -> Design:
    return Design(
        architecture=Architecture(
            summary="단일 Node 백엔드",
            shape="브라우저 → Node → PostgreSQL",
            data_flow="전송 → 기록 → 브로드캐스트",
        ),
        components=components,
    )


def _notes(runs_dir: str) -> list[str]:
    return [g["note"] for g in store.get_all_gaps(SLUG, runs_dir=runs_dir)]


def test_no_filtering_at_all_is_recorded(runs_dir: str):
    """★ 전부 통과하면 프롬프트 반례가 안 먹힌 것이다 — 조용히 넘기지 않는다.

    이게 없으면 `necessity`·`needs_comparison`이 사실상 항상 true인 상태로 회귀해도
    파이프라인은 정상으로 보인다 (그게 `analyze` 시절의 상태였다).
    """
    components = [_component("실시간 메시지 전달"), _component("인증", priority=2)]

    _record_gaps(SLUG, _design(components), components, [])

    notes = _notes(runs_dir)
    assert any("needs_comparison이 전부 true" in n for n in notes)
    assert any("necessity가 전부 essential/valuable" in n for n in notes)


def test_filtering_present_leaves_no_warning(runs_dir: str):
    """반대 방향 — 걸러낸 것이 있으면 경고가 없어야 한다. 경고가 늘 뜨면 무시된다."""
    components = _all_four()
    selected = select_passing_components(components, 10)

    _record_gaps(SLUG, _design(components), selected, [])

    notes = _notes(runs_dir)
    assert not any("전부" in n for n in notes), notes


def test_empty_search_hints_are_recorded(runs_dir: str):
    """통과 결정 지점의 `search_hints`가 비면 조사가 얕아진다 (불변식 16)."""
    passing = _component("실시간 메시지 전달")
    passing.search_hints = []

    _record_gaps(SLUG, _design([passing]), [passing], [])

    assert any("search_hints가 비어" in n for n in _notes(runs_dir))


def test_no_components_at_all_is_recorded(runs_dir: str):
    _record_gaps(SLUG, _design([]), [], [])

    assert any("결정 지점이 도출되지 않음" in n for n in _notes(runs_dir))
