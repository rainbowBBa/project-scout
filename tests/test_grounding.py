"""grounding 검증 장치를 검사한다 — LLM도 네트워크도 쓰지 않는다.

검증하는 주장: **judge는 dossier 밖을 인용할 수 없다.** 없는 fact_id를 인용하면 코드가
SQL로 잡아내고, 재판정에도 남으면 confidence가 강등된다. 이 대조가 없으면 judge가
사실을 지어내도 알 수 없고, 그러면 이 도구는 그냥 LLM에게 물어보는 것과 같아진다
(불변식 4).

`test_search_approval`과 같은 성격이다 — 판단의 품질이 아니라 배선을 본다.
"""

import asyncio
import sqlite3
from pathlib import Path
from typing import Literal

import pytest
from langchain_core.runnables import RunnableLambda
from scout import grounding, store
from scout.schemas import Candidate, Component, Fact, Interview, Verdict
from scout.stages.verify import _verify_candidate

SLUG = "test-run"


@pytest.fixture
def runs_dir(tmp_path: Path) -> str:
    return str(tmp_path)


def _candidate() -> Candidate:
    return Candidate(
        component="실시간 메시지 전달",
        name="socket.io",
        kind="library",
        what_it_is="재연결·룸·폴백을 내장한 실시간 통신 라이브러리",
        dossier=[
            Fact(
                id="npm.last_release",
                label="마지막 릴리스",
                value="2025-06-01",
                url=None,
                retrieved_at="2026-09-03T00:00:00Z",
            ),
            Fact(
                id="gh.last_commit",
                label="마지막 커밋",
                value="2026-08-20",
                url=None,
                retrieved_at="2026-09-03T00:00:00Z",
            ),
        ],
    )


def _verdict(
    citations: list[str], confidence: Literal["high", "medium", "low"] = "high"
) -> Verdict:
    return Verdict(
        candidate="socket.io",
        component="실시간 메시지 전달",
        solves_it=True,
        solves_reason="재연결·룸을 내장해 요소 요구를 직접 충족",
        pros=["재연결 자동"],
        cons=["독자 프로토콜"],
        caveats=[],
        confidence=confidence,
        citations=citations,
        unsupported_claims=[],
    )


def _seed(runs_dir: str) -> Candidate:
    candidate = _candidate()
    store.upsert_candidate(SLUG, candidate, runs_dir=runs_dir)
    return candidate


def _grounding_violations(runs_dir: str, candidate: str) -> int:
    conn = sqlite3.connect(Path(runs_dir) / SLUG / "scout.db")
    try:
        row = conn.execute(
            "SELECT grounding_violations FROM verdicts WHERE slug = ? AND candidate = ?",
            (SLUG, candidate),
        ).fetchone()
    finally:
        conn.close()
    return row[0]


# ── 검출 (SQL 대조) ──────────────────────────────────────────────────────


def test_ungrounded_citation_is_detected(runs_dir: str):
    """dossier에 없는 id를 인용한 Verdict를 손으로 주입하면 잡힌다."""
    _seed(runs_dir)
    store.upsert_verdict(
        SLUG,
        _verdict(["npm.last_release", "gh.stars", "osv.vulns"]),
        runs_dir=runs_dir,
    )

    assert grounding.ungrounded(SLUG, "socket.io", runs_dir=runs_dir) == [
        "gh.stars",
        "osv.vulns",
    ]


def test_grounded_citations_pass(runs_dir: str):
    _seed(runs_dir)
    store.upsert_verdict(SLUG, _verdict(["npm.last_release", "gh.last_commit"]), runs_dir=runs_dir)

    assert grounding.ungrounded(SLUG, "socket.io", runs_dir=runs_dir) == []


def test_other_candidates_dossier_does_not_ground_this_one(runs_dir: str):
    """다른 후보의 사실로는 인용이 성립하지 않는다 — 조인이 candidate까지 본다."""
    _seed(runs_dir)
    store.upsert_facts(
        SLUG,
        "ws",
        [
            Fact(
                id="npm.weekly_downloads",
                label="주간 다운로드",
                value="70000000",
                url=None,
                retrieved_at="2026-09-03T00:00:00Z",
            )
        ],
        runs_dir=runs_dir,
    )
    store.upsert_verdict(SLUG, _verdict(["npm.weekly_downloads"]), runs_dir=runs_dir)

    assert grounding.ungrounded(SLUG, "socket.io", runs_dir=runs_dir) == ["npm.weekly_downloads"]


# ── 강등 규칙 ────────────────────────────────────────────────────────────


def test_strip_ungrounded_moves_violation_to_unsupported_claims():
    stripped = grounding.strip_ungrounded(_verdict(["npm.last_release", "gh.stars"]), ["gh.stars"])

    assert stripped.citations == ["npm.last_release"]
    assert any("gh.stars" in c for c in stripped.unsupported_claims)


def test_lower_confidence_bottoms_out_at_low():
    assert grounding.lower_confidence(_verdict([], "high")).confidence == "medium"
    assert grounding.lower_confidence(_verdict([], "medium")).confidence == "low"
    assert grounding.lower_confidence(_verdict([], "low")).confidence == "low"


def test_force_low_skips_the_middle_step():
    """재판정에도 위반이 남으면 한 단계가 아니라 바닥까지 내린다."""
    assert grounding.force_low(_verdict([], "high")).confidence == "low"


def test_degrade_if_uncited():
    """근거 0개 판정은 판정이 아니다."""
    degraded = grounding.degrade_if_uncited(_verdict([], "high"))

    assert degraded.confidence == "medium"
    assert grounding.NO_CITATION_CLAIM in degraded.unsupported_claims

    kept = _verdict(["npm.last_release"], "high")
    assert grounding.degrade_if_uncited(kept) is kept


# ── 재판정 루프 배선 ─────────────────────────────────────────────────────


class _StubLLM:
    """판정 LLM 대역. 호출 순서대로 미리 정해둔 Verdict를 돌려준다."""

    def __init__(self, *verdicts: Verdict) -> None:
        self.verdicts = list(verdicts)
        self.prompts: list[str] = []

    def with_structured_output(self, _model, include_raw: bool = False):
        def _run(messages):
            self.prompts.append(str(messages))
            idx = min(len(self.prompts) - 1, len(self.verdicts) - 1)
            return {"parsed": self.verdicts[idx], "raw": None}

        return RunnableLambda(_run)


def _run_verify_one(llm: _StubLLM, candidate: Candidate, runs_dir: str) -> Verdict:
    component = Component(
        name="실시간 메시지 전달",
        kind="feature",
        role_in_design="사용자 간 즉시 전달이 서비스의 핵심",
        decision_question="즉시 전달을 감당할 전달 계층은 무엇인가",
        necessity="essential",
        necessity_reason="없으면 서비스가 성립하지 않는다",
        priority=1,
        approach_notes="WebSocket 기반",
    )
    interview = Interview(
        raw_description="협업 메모 앱",
        refined_brief="3인 팀이 3개월 안에 만드는 협업 메모 앱",
        assumptions=["동시 접속 100명 규모"],
    )
    return asyncio.run(
        _verify_candidate(
            SLUG,
            candidate,
            component,
            interview,
            llm,
            asyncio.Semaphore(1),
            runs_dir=runs_dir,
        )
    )


def test_violation_triggers_one_reground(runs_dir: str):
    """1차 위반 → 위반 목록을 붙여 재판정. 2차가 깨끗하면 강등하지 않는다."""
    candidate = _seed(runs_dir)
    llm = _StubLLM(
        _verdict(["npm.last_release", "gh.stars"]),
        _verdict(["npm.last_release", "gh.last_commit"]),
    )

    verdict = _run_verify_one(llm, candidate, runs_dir)

    assert len(llm.prompts) == 2
    assert "gh.stars" in llm.prompts[1]  # 위반 목록이 재판정 프롬프트에 들어갔다
    assert verdict.confidence == "high"
    assert verdict.citations == ["npm.last_release", "gh.last_commit"]
    assert _grounding_violations(runs_dir, "socket.io") == 0


def test_persistent_violation_degrades_and_is_recorded(runs_dir: str):
    """2차에도 위반이면 더 묻지 않고 low로 내리고, 위반 횟수를 남긴다."""
    candidate = _seed(runs_dir)
    llm = _StubLLM(_verdict(["npm.last_release", "gh.stars"]))

    verdict = _run_verify_one(llm, candidate, runs_dir)

    assert len(llm.prompts) == 2  # 재판정은 1회까지 — 무한 루프가 아니다
    assert verdict.confidence == "low"
    assert verdict.citations == ["npm.last_release"]
    assert any("gh.stars" in c for c in verdict.unsupported_claims)
    assert _grounding_violations(runs_dir, "socket.io") == 1

    stored = store.get_verdicts(SLUG, runs_dir=runs_dir)[0]
    assert stored.citations == ["npm.last_release"]
    assert grounding.ungrounded(SLUG, "socket.io", runs_dir=runs_dir) == []


def test_all_citations_bogus_degrades_twice_and_keeps_count(runs_dir: str):
    """인용을 전부 걷어내면 '근거 0개' 규칙까지 걸린다 — 위반 횟수는 살아남는다."""
    candidate = _seed(runs_dir)
    llm = _StubLLM(_verdict(["gh.stars"]))

    verdict = _run_verify_one(llm, candidate, runs_dir)

    assert verdict.citations == []
    assert verdict.confidence == "low"
    assert grounding.NO_CITATION_CLAIM in verdict.unsupported_claims
    assert _grounding_violations(runs_dir, "socket.io") == 1
