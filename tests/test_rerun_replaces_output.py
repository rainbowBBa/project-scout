"""재실행이 산출물을 교체하는지 검사한다 — LLM도 네트워크도 쓰지 않는다.

검증하는 주장: **재실행이 이전 실행의 후보·판정을 남기지 않는다.**

PK upsert만으로는 부족하다. `design`이 결정 지점 **이름을 다르게** 만들면 이전 실행의
후보가 다른 키로 남아 고아가 된다 — 실측에서 `candidates`가 6행이었고 `socket.io`가
`'실시간 메시지 전달'`과 `'실시간 메시지 전달 계층'` 두 이름으로 들어 있었다.
`evaluate`는 `store.get_candidates(slug)`를 읽으므로 사라진 요소의 후보까지 채점한다.

`v24`에서 고친 상태 리듀서 누적과는 다른 층이다 — 그건 LangGraph 상태, 이건 DB다.
"""

from pathlib import Path

import pytest
from scout import store
from scout.schemas import Candidate, Component, Fact, Verdict

SLUG = "rerun"


@pytest.fixture
def runs_dir(tmp_path: Path) -> str:
    return str(tmp_path)


def _component(name: str) -> Component:
    return Component(
        name=name,
        kind="feature",
        role_in_design="역할",
        decision_question="무엇을 정할까",
        necessity="essential",
        necessity_reason="핵심",
        priority=1,
        approach_notes="",
    )


def _candidate(component: str, name: str) -> Candidate:
    return Candidate(
        component=component,
        name=name,
        kind="library",
        what_it_is="설명",
        dossier=[
            Fact(
                id="npm.license",
                label="라이선스",
                value="MIT",
                url=None,
                retrieved_at="2026-09-03T00:00:00Z",
            )
        ],
        dossier_gaps=["GitHub 미확인"],
    )


def _verdict(component: str, name: str) -> Verdict:
    return Verdict(
        candidate=name,
        component=component,
        solves_it=True,
        solves_reason="된다",
        pros=[],
        cons=[],
        caveats=[],
        confidence="high",
        citations=["npm.license"],
    )


def _run(component: str, runs_dir: str) -> None:
    """한 번의 파이프라인 실행이 쓰는 것을 흉내낸다 — 단계 순서를 그대로 따른다."""
    store.upsert_components(SLUG, [_component(component)], runs_dir=runs_dir)

    store.clear_stage_output(SLUG, "search", runs_dir=runs_dir)
    store.upsert_candidate(SLUG, _candidate(component, "socket.io"), runs_dir=runs_dir)

    store.clear_stage_output(SLUG, "verify", runs_dir=runs_dir)
    store.upsert_verdict(SLUG, _verdict(component, "socket.io"), runs_dir=runs_dir)

    store.clear_stage_output(SLUG, "evaluate", runs_dir=runs_dir)
    store.set_score(
        SLUG, "socket.io", "overall", 4, "judged", "이유", runs_dir=runs_dir
    )


def test_renamed_component_leaves_no_orphan(runs_dir: str):
    """★ 실측된 실패 모드 — design이 요소 이름을 바꾸면 이전 후보가 고아로 남았다."""
    _run("실시간 메시지 전달", runs_dir)
    _run("실시간 메시지 전달 계층", runs_dir)

    candidates = store.get_candidates(SLUG, runs_dir=runs_dir)

    assert len(candidates) == 1, (
        f"후보가 {len(candidates)}개 남았다 — 이전 실행의 고아다. "
        "evaluate가 사라진 요소의 후보까지 채점한다"
    )
    assert candidates[0].component == "실시간 메시지 전달 계층"


def test_verdicts_and_scores_are_replaced_too(runs_dir: str):
    _run("요소 A", runs_dir)
    _run("요소 B", runs_dir)

    assert len(store.get_verdicts(SLUG, runs_dir=runs_dir)) == 1
    assert len(store.get_scores(SLUG, runs_dir=runs_dir)) == 1
    # citations도 함께 비워야 grounding 대조가 낡은 인용을 보지 않는다
    assert len(store.get_citations(SLUG, "socket.io", runs_dir=runs_dir)) == 1


def test_gaps_do_not_pile_up_across_runs(runs_dir: str):
    """단계가 자기 이름으로 남긴 gap과 후보에 달린 gap이 재실행마다 쌓이지 않는다."""
    for _ in range(3):
        _run("요소 A", runs_dir)
        store.add_gap(SLUG, "search", "웹검색 거부", runs_dir=runs_dir)

    notes = [g["note"] for g in store.get_all_gaps(SLUG, runs_dir=runs_dir)]

    assert notes.count("웹검색 거부") == 1, f"단계 gap이 쌓였다: {notes}"
    assert notes.count("GitHub 미확인") == 1, f"후보 gap이 쌓였다: {notes}"


def test_unknown_stage_is_rejected(runs_dir: str):
    """단계 이름을 오타 내면 조용히 아무것도 안 비우는 것보다 즉시 실패가 낫다."""
    with pytest.raises(ValueError):
        store.clear_stage_output(SLUG, "serch", runs_dir=runs_dir)
