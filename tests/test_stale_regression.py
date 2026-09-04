"""낡은 사실이 최종 추천을 바꾸는지 검사한다 — LLM도 네트워크도 쓰지 않는다.

검증하는 주장: **아카이브된·릴리스가 끊긴 후보는 최종 순위에서 1위가 되지 않는다.**

이중 안전망(불변식 5)이므로 **판정과 계산 중 하나만 작동해도 통과한다** — 두 경로를
각각 혼자 세워놓고 본다. 한 시나리오에서 같이 보면 한쪽이 죽어도 통과한다.

날짜는 고정 문자열이다 — `rubric`의 상한이 1095일이라 2019년 릴리스는 언제 돌려도
최하점이고 `gh.archived`는 날짜를 보지 않는다.
"""

import asyncio
from pathlib import Path

import pytest
from langchain_core.runnables import RunnableLambda
from scout import rubric, store
from scout.schemas import (
    Candidate,
    CandidateScore,
    Component,
    ElementPick,
    Fact,
    Interview,
    Verdict,
)
from scout.stages.evaluate import (
    _evaluate_component,
    normalize,
    store_computed_scores,
)
from scout.stages.report import build_report_context

SLUG = "stale-regression"
COMPONENT = "HTTP 클라이언트"
STALE = "request"
FRESH = "undici"

# 탈락 사유에 인용돼야 하는 사실. judge 경로가 이 문장을 근거로 든다.
STALE_RELEASE = "2019-05-01"


@pytest.fixture
def runs_dir(tmp_path: Path) -> str:
    return str(tmp_path)


def _fact(fact_id: str, label: str, value: str) -> Fact:
    return Fact(
        id=fact_id,
        label=label,
        value=value,
        url=None,
        retrieved_at="2026-09-03T00:00:00Z",
    )


def _stale_facts() -> list[Fact]:
    """낡음이 세 신호에 동시에 나타난다 — 실제 아카이브 패키지의 모습이다."""
    return [
        _fact("npm.last_release", "마지막 릴리스", STALE_RELEASE),
        _fact("npm.license", "라이선스", "Apache-2.0"),
        _fact("gh.last_commit", "마지막 커밋", "2020-02-11"),
        _fact("gh.archived", "보관 여부", "True"),
        _fact("gh.contributors", "기여자", "300"),
    ]


def _fresh_facts() -> list[Fact]:
    return [
        _fact("npm.last_release", "마지막 릴리스", "2026-08-20"),
        _fact("npm.license", "라이선스", "MIT"),
        _fact("gh.last_commit", "마지막 커밋", "2026-08-28"),
        _fact("gh.contributors", "기여자", "120"),
    ]


def _candidate(name: str, facts: list[Fact], what: str) -> Candidate:
    return Candidate(
        component=COMPONENT,
        name=name,
        kind="library",
        what_it_is=what,
        dossier=facts,
    )


def _candidates() -> list[Candidate]:
    return [
        _candidate(STALE, _stale_facts(), "구세대 HTTP 클라이언트"),
        _candidate(FRESH, _fresh_facts(), "Node 코어 팀이 만든 HTTP 클라이언트"),
    ]


def _component() -> Component:
    return Component(
        name=COMPONENT,
        kind="integration",
        role_in_design="외부 API 호출을 담당한다",
        decision_question="외부 호출에 쓸 HTTP 클라이언트는 무엇인가",
        alternatives=[STALE, FRESH],
        necessity="essential",
        necessity_reason="외부 요약 API 호출이 3인 팀 일정의 전제다",
        priority=1,
        approach_notes="",
        search_hints=["node http client"],
    )


def _interview() -> Interview:
    return Interview(
        raw_description="AI 요약이 있는 팀 채팅 앱",
        refined_brief="3인 TypeScript 팀이 3개월 안에 만드는 사내 200명 팀 채팅 앱, 월 $200",
        assumptions=["동시 접속 100명 규모"],
    )


def _verdict(name: str, *, solves_it: bool, reason: str, citations: list[str]) -> Verdict:
    return Verdict(
        candidate=name,
        component=COMPONENT,
        solves_it=solves_it,
        solves_reason=reason,
        pros=[] if not solves_it else ["요구를 충족한다"],
        cons=[],
        caveats=[],
        confidence="high",
        citations=citations,
    )


# ── 경로 A · 계산 (rubric) ───────────────────────────────────────────────


def test_archived_repo_scores_lowest_maturity():
    """`gh.archived`는 다른 신호를 보지 않고 1이다 — 기여자 300명도 구제하지 않는다."""
    score, reason = rubric.maturity(_stale_facts())

    assert score == 1
    assert "gh.archived" in reason


def test_stale_release_alone_scores_lowest_maturity():
    """아카이브 표시가 없어도 릴리스가 끊기면 최하점이다 — 신호 하나로도 잡힌다."""
    facts = [f for f in _stale_facts() if f.id != "gh.archived"]

    score, reason = rubric.maturity(facts)

    assert score == 1
    assert "npm.last_release" in reason and "일 전" in reason


def test_fresh_candidate_is_not_penalized():
    """반대 방향 — 계산이 모두를 1로 깎으면 순위가 생기지 않는다."""
    assert rubric.maturity(_fresh_facts())[0] == 5


def test_computed_scores_are_stored_for_the_rejected_candidate_too(runs_dir: str):
    """탈락 후보의 계산 점수도 남는다 — 없으면 이중 안전망이 작동한 증거가 사라진다."""
    computed = store_computed_scores(SLUG, _candidates(), runs_dir=runs_dir)

    assert computed[STALE][0][0] == 1
    stored = {
        (s["candidate"], s["criterion"]): s
        for s in store.get_scores(SLUG, runs_dir=runs_dir)
    }
    maturity = stored[(STALE, "maturity")]
    assert maturity["score"] == 1
    assert maturity["source"] == rubric.COMPUTED
    assert "gh.archived" in maturity["reason"], "왜 1인지가 보고서에 안 남는다"


# ── 경로 B · 판정 (judge) ────────────────────────────────────────────────


def _run_component(
    runs_dir: str, verdicts: list[Verdict], llm=None
) -> tuple[ElementPick | None, list[str]]:
    candidates = _candidates()
    computed = store_computed_scores(SLUG, candidates, runs_dir=runs_dir)
    return asyncio.run(
        _evaluate_component(
            SLUG,
            COMPONENT,
            _component(),
            verdicts,
            {c.name: c for c in candidates},
            computed,
            _interview(),
            llm,
            asyncio.Semaphore(1),
            runs_dir=runs_dir,
        )
    )


def test_judge_rejection_drops_it_and_cites_the_release_fact(runs_dir: str):
    """판정 경로 — judge가 탈락시키면 순위에 들어가지 않는다.

    사유는 judge가 쓴 문장을 그대로 인용하므로, "마지막 릴리스"가 남는 것이 곧 사실이
    판단을 바꿨다는 증거다.
    """
    verdicts = [
        _verdict(
            STALE,
            solves_it=False,
            reason=f"마지막 릴리스가 {STALE_RELEASE}로 끊겼고 저장소가 보관됐다 — "
            "3개월 일정에서 유지보수 부재를 감당할 수 없다",
            citations=["npm.last_release", "gh.archived"],
        ),
        _verdict(
            FRESH,
            solves_it=True,
            reason="활발히 유지되고 Node 코어와 함께 간다",
            citations=["npm.last_release"],
        ),
    ]

    pick, _ = _run_component(runs_dir, verdicts)

    assert pick is not None and pick.winner == FRESH
    assert STALE not in pick.ranking, "탈락 후보가 순위에 남았다"

    picks = {p["candidate"]: p for p in store.get_picks(SLUG, runs_dir=runs_dir)}
    assert picks[STALE]["rank"] is None
    assert "마지막 릴리스" in picks[STALE]["rejected_reason"]


def test_rejected_candidate_stays_visible_in_the_report(runs_dir: str):
    """탈락은 삭제가 아니다 — 왜 떨어졌는지가 보고서에 남는다 (불변식 12)."""
    store.upsert_components(SLUG, [_component()], runs_dir=runs_dir)
    for candidate in _candidates():
        store.upsert_candidate(SLUG, candidate, runs_dir=runs_dir)
    verdicts = [
        _verdict(
            STALE,
            solves_it=False,
            reason=f"마지막 릴리스 {STALE_RELEASE} — 유지보수가 끊겼다",
            citations=["npm.last_release"],
        ),
        _verdict(FRESH, solves_it=True, reason="활발히 유지된다", citations=["npm.last_release"]),
    ]
    for verdict in verdicts:
        store.upsert_verdict(SLUG, verdict, runs_dir=runs_dir)
    _run_component(runs_dir, verdicts)

    ctx = build_report_context(SLUG, runs_dir=runs_dir)

    assert [row["candidate"] for row in ctx["stack"]] == [FRESH]
    rejection = next(r for r in ctx["rejections"] if r["candidate"] == STALE)
    assert "마지막 릴리스" in rejection["reason"]


# ── 두 경로 중 하나만 작동해도 통과한다 ─────────────────────────────────


class _BlindJudge:
    """낡은 사실을 무시하는 judge 대역 — 두 후보를 동점으로 주고 낡은 쪽을 1위로 쓴다."""

    def __init__(self) -> None:
        self.calls = 0

    def with_structured_output(self, _model, include_raw: bool = False):
        def _run(_messages):
            self.calls += 1
            return {
                "parsed": ElementPick(
                    component=COMPONENT,
                    scores=[
                        CandidateScore(
                            candidate=STALE,
                            overall=4,
                            score_reason="익숙한 API라 3인 팀에 유리 — 2위와 0점 차",
                        ),
                        CandidateScore(
                            candidate=FRESH,
                            overall=4,
                            score_reason="성능은 좋지만 API가 낯설다 — 1위와 0점 차",
                        ),
                    ],
                    ranking=[STALE, FRESH],
                    winner=STALE,
                    winner_reason="3인 팀이 이미 아는 API다 — 2위와 0점 차",
                    runner_up_note=f"{FRESH}도 합리적이다",
                    margin="close",
                ),
                "raw": None,
            }

        return RunnableLambda(_run)


def test_computation_overrides_the_judge_when_scores_tie(runs_dir: str):
    """계산 경로 — judge가 낡은 후보를 1위로 써도 동점 정렬의 `maturity`가 뒤집는다."""
    verdicts = [
        _verdict(STALE, solves_it=True, reason="익숙한 API", citations=["npm.license"]),
        _verdict(FRESH, solves_it=True, reason="활발히 유지된다", citations=["npm.license"]),
    ]

    pick, warnings = _run_component(runs_dir, verdicts, llm=_BlindJudge())

    assert pick is not None
    assert pick.ranking == [FRESH, STALE], "계산이 순위를 뒤집지 못했다"
    assert pick.winner == FRESH
    assert any("순위 1위" in w for w in warnings), (
        "judge와 순위가 어긋난 사실이 기록되지 않았다"
    )


def test_normalize_tiebreak_uses_maturity_directly():
    """위 시나리오의 핵심만 떼어 본다 — 동점이면 `maturity`가 순서를 정한다."""
    computed = {
        STALE: (rubric.maturity(_stale_facts()), rubric.risk(_stale_facts())),
        FRESH: (rubric.maturity(_fresh_facts()), rubric.risk(_fresh_facts())),
    }
    pick = ElementPick(
        component=COMPONENT,
        scores=[
            CandidateScore(candidate=STALE, overall=4, score_reason="동점"),
            CandidateScore(candidate=FRESH, overall=4, score_reason="동점"),
        ],
        ranking=[STALE, FRESH],
        winner=STALE,
        winner_reason="동점",
        runner_up_note="",
        margin="close",
    )

    normalized, _ = normalize(pick, COMPONENT, [STALE, FRESH], computed)

    assert normalized.ranking == [FRESH, STALE]


@pytest.mark.parametrize("judge_sees_it", [True, False])
def test_stale_candidate_never_wins_either_way(runs_dir: str, judge_sees_it: bool):
    """★ 이중 안전망의 정의 — 판정과 계산 중 **하나만** 작동해도 결과가 같다."""
    if judge_sees_it:
        verdicts = [
            _verdict(
                STALE,
                solves_it=False,
                reason=f"마지막 릴리스 {STALE_RELEASE} — 유지보수가 끊겼다",
                citations=["npm.last_release"],
            ),
            _verdict(FRESH, solves_it=True, reason="활발히 유지된다", citations=["npm.license"]),
        ]
        llm = None
    else:
        verdicts = [
            _verdict(STALE, solves_it=True, reason="익숙한 API", citations=["npm.license"]),
            _verdict(FRESH, solves_it=True, reason="활발히 유지된다", citations=["npm.license"]),
        ]
        llm = _BlindJudge()

    pick, _ = _run_component(runs_dir, verdicts, llm=llm)

    assert pick is not None and pick.winner == FRESH
