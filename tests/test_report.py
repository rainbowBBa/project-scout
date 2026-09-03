"""report 단계 — scout.db를 읽어 조립한 컨텍스트와 렌더링 결과를 검사한다.

LLM도 네트워크도 쓰지 않는 단계라 store에 손으로 시드하고 결과만 본다
(stages/5-report.md 완료 기준).
"""

from pathlib import Path

import pytest
from scout import store
from scout.schemas import (
    Architecture,
    Candidate,
    Component,
    Fact,
    FinalDesign,
    Interview,
    Verdict,
)
from scout.stages.report import build_report_context, render_report

SLUG = "test-run"


@pytest.fixture
def runs_dir(tmp_path: Path) -> str:
    return str(tmp_path)


def _seed_basic(runs_dir: str) -> None:
    store.upsert_run(
        SLUG,
        "사내 200명 팀 채팅 앱",
        "2026-09-03T00:00:00Z",
        Interview(
            raw_description="사내 200명 팀 채팅 앱",
            refined_brief="3인 팀이 3개월 안에 만드는 사내 200명 팀 채팅 앱",
            assumptions=["동시 접속 100명 규모"],
        ),
        runs_dir=runs_dir,
    )
    store.upsert_components(
        SLUG,
        [
            Component(
                name="실시간 메시지 전달",
                kind="feature",
                role_in_design="사용자 간 즉시 전달이 핵심",
                decision_question="즉시 전달을 감당할 전달 계층은 무엇인가",
                necessity="essential",
                necessity_reason="없으면 서비스가 성립하지 않는다",
                priority=1,
                approach_notes="WebSocket 기반",
            ),
            Component(
                name="메시지 전문검색",
                kind="feature",
                role_in_design="과거 대화를 찾는다",
                decision_question="과거 대화를 찾는 검색 방식은 무엇인가",
                necessity="defer",
                necessity_reason="200명이면 LIKE로 충분",
                priority=5,
                approach_notes="",
            ),
            Component(
                name="파일 첨부",
                kind="feature",
                role_in_design="문서를 공유한다",
                decision_question="문서 공유를 감당할 저장·전송 방식은 무엇인가",
                necessity="valuable",
                necessity_reason="핵심은 아니지만 있으면 좋다",
                priority=4,
                approach_notes="",
            ),
        ],
        runs_dir=runs_dir,
    )

    winner = Candidate(
        component="실시간 메시지 전달",
        name="socket.io",
        kind="library",
        what_it_is="재연결·룸을 내장한 실시간 통신 라이브러리",
        dossier=[
            Fact(
                id="npm.last_release",
                label="마지막 릴리스",
                value="2026-06-01",
                url="https://npmjs.com/package/socket.io",
                retrieved_at="2026-09-03T00:00:00Z",
            )
        ],
    )
    runner_up = Candidate(
        component="실시간 메시지 전달",
        name="ws",
        kind="library",
        what_it_is="저수준 WebSocket 라이브러리",
        dossier=[
            Fact(
                id="npm.last_release",
                label="마지막 릴리스",
                value="2026-05-01",
                url=None,
                retrieved_at="2026-09-03T00:00:00Z",
            )
        ],
    )
    rejected = Candidate(
        component="실시간 메시지 전달",
        name="sockjs",
        kind="library",
        what_it_is="폴백 위주 라이브러리",
        dossier_gaps=["gh 조회 실패: rate limit"],
    )
    for c in (winner, runner_up, rejected):
        store.upsert_candidate(SLUG, c, runs_dir=runs_dir)

    store.upsert_verdict(
        SLUG,
        Verdict(
            candidate="socket.io",
            component="실시간 메시지 전달",
            solves_it=True,
            solves_reason="재연결·룸을 내장해 요구를 직접 충족",
            pros=["재연결 자동"],
            cons=["독자 프로토콜"],
            caveats=["대규모 트래픽엔 별도 검토 필요"],
            confidence="high",
            citations=["npm.last_release"],
        ),
        runs_dir=runs_dir,
    )
    store.upsert_verdict(
        SLUG,
        Verdict(
            candidate="ws",
            component="실시간 메시지 전달",
            solves_it=True,
            solves_reason="안정적이지만 재연결·룸을 직접 구현해야 함",
            pros=["가볍다"],
            cons=["직접 구현 부담"],
            caveats=[],
            confidence="medium",
            citations=["npm.last_release"],
        ),
        runs_dir=runs_dir,
    )
    store.upsert_verdict(
        SLUG,
        Verdict(
            candidate="sockjs",
            component="실시간 메시지 전달",
            solves_it=False,
            solves_reason="마지막 릴리스 1,690일 전 — 유지보수가 끊겼다",
            pros=[],
            cons=[],
            caveats=[],
            confidence="high",
            citations=[],
        ),
        runs_dir=runs_dir,
    )

    store.set_score(SLUG, "socket.io", "maturity", 5, "computed", "릴리스 최근", runs_dir=runs_dir)
    store.set_score(SLUG, "socket.io", "risk", 5, "computed", "취약점 없음", runs_dir=runs_dir)
    store.set_score(
        SLUG,
        "socket.io",
        "overall",
        4,
        "judged",
        "제약상 재연결 내장이 중요 — 2위와 1점 차",
        runs_dir=runs_dir,
    )
    store.set_score(SLUG, "ws", "maturity", 4, "computed", "릴리스 다소 최근", runs_dir=runs_dir)
    store.set_score(
        SLUG, "ws", "risk", None, "unavailable", "위험 신호 없음", runs_dir=runs_dir
    )
    store.set_score(
        SLUG, "ws", "overall", 3, "judged", "직접 구현 부담이 감점 요인", runs_dir=runs_dir
    )
    store.set_score(
        SLUG, "sockjs", "maturity", None, "unavailable", "릴리스 신호 없음", runs_dir=runs_dir
    )
    store.set_score(
        SLUG, "sockjs", "risk", None, "unavailable", "위험 신호 없음", runs_dir=runs_dir
    )

    store.add_pick(
        SLUG,
        "실시간 메시지 전달",
        "socket.io",
        rank=1,
        winner_reason="제약상 재연결 내장이 중요 — 2위와 1점 차",
        runner_up_note="ws도 합리적 선택지다",
        margin="close",
        runs_dir=runs_dir,
    )
    store.add_pick(SLUG, "실시간 메시지 전달", "ws", rank=2, runs_dir=runs_dir)
    store.add_pick(
        SLUG,
        "실시간 메시지 전달",
        "sockjs",
        rejected_reason="마지막 릴리스 1,690일 전 — 유지보수가 끊겼다",
        runs_dir=runs_dir,
    )


def test_context_has_confirmed_stack_with_close_margin(runs_dir: str):
    _seed_basic(runs_dir)

    ctx = build_report_context(SLUG, runs_dir=runs_dir)

    assert len(ctx["stack"]) == 1
    row = ctx["stack"][0]
    assert row["candidate"] == "socket.io"
    assert row["margin"] == "close"
    assert row["overall"]["score"] == 4
    assert "재연결 내장" in row["winner_reason"]


def test_context_separates_deferred_from_skipped(runs_dir: str):
    """defer 요소와, max-components에 밀려 아예 다루지 않은 valuable 요소는 다른 섹션이다."""
    _seed_basic(runs_dir)

    ctx = build_report_context(SLUG, runs_dir=runs_dir)

    assert [c.name for c in ctx["deferred"]] == ["메시지 전문검색"]
    assert [c.name for c in ctx["skipped"]] == ["파일 첨부"]


def test_context_marks_unavailable_scores_and_grounding_violations(runs_dir: str):
    _seed_basic(runs_dir)

    ctx = build_report_context(SLUG, runs_dir=runs_dir)

    element = ctx["elements"][0]
    sockjs = next(c for c in element["candidates"] if c["name"] == "sockjs")
    assert sockjs["rank"] is None
    assert sockjs["maturity"] is None or sockjs["maturity"]["score"] is None
    assert ctx["grounding_violations_total"] == 0


def test_no_winner_recorded_when_all_candidates_rejected(runs_dir: str):
    """통과 후보가 0개인 요소는 확정 스택에서 빠지고 no_winner로 경고 대상이 된다."""
    _seed_basic(runs_dir)
    store.upsert_candidate(
        SLUG,
        Candidate(
            component="파일 첨부",
            name="s3-presigned",
            kind="method",
            what_it_is="사전 서명 URL 업로드",
        ),
        runs_dir=runs_dir,
    )
    store.upsert_verdict(
        SLUG,
        Verdict(
            candidate="s3-presigned",
            component="파일 첨부",
            solves_it=False,
            solves_reason="이 방식만으로는 바이러스 스캔 요구를 못 채운다",
            pros=[],
            cons=[],
            caveats=[],
            confidence="medium",
            citations=[],
        ),
        runs_dir=runs_dir,
    )
    store.add_pick(
        SLUG,
        "파일 첨부",
        "s3-presigned",
        rejected_reason="이 방식만으로는 바이러스 스캔 요구를 못 채운다",
        runs_dir=runs_dir,
    )

    ctx = build_report_context(SLUG, runs_dir=runs_dir)

    assert "파일 첨부" in ctx["no_winner"]
    assert "파일 첨부" not in [c.name for c in ctx["skipped"]]
    assert all(row["component"] != "파일 첨부" for row in ctx["stack"])


def test_render_is_self_contained_and_shows_score_reason_under_bar(runs_dir: str):
    _seed_basic(runs_dir)
    ctx = build_report_context(SLUG, runs_dir=runs_dir)

    html = render_report(ctx)

    assert "<script" not in html
    assert "cdn." not in html
    assert "근접" in html  # margin close 배지
    assert "computed" in html and "judged" in html and "근거 없음" in html
    assert "제약상 재연결 내장이 중요" in html  # score_reason
    idx_bar = html.index('style="width: 80%"')  # overall=4 → 80%
    idx_reason = html.index("제약상 재연결 내장이 중요", idx_bar)
    assert idx_reason - idx_bar < 400  # 막대 바로 아래에 이유가 붙는다
    assert "<details" in html and "</details>" in html


def test_empty_sections_show_reason_not_disappear(runs_dir: str):
    store.upsert_run(
        SLUG,
        "빈 프로젝트",
        "2026-09-03T00:00:00Z",
        Interview(
            raw_description="빈 프로젝트", refined_brief="아직 아무 요소도 없다", assumptions=[]
        ),
        runs_dir=runs_dir,
    )

    ctx = build_report_context(SLUG, runs_dir=runs_dir)
    html = render_report(ctx)

    assert ctx["stack"] == []
    assert "해당 없음" in html


# ── STEP 11 · 권장 설계 · v1 대조 · 이미 정해진 부분 ─────────────────────


def _seed_designs(runs_dir: str) -> None:
    """기본틀(v1)과 확정 설계(v2)를 시드한다 — 같은 이름의 필드가 대조 재료다."""
    store.upsert_design(
        SLUG,
        Architecture(
            summary="단일 Node 백엔드가 실시간 연결과 REST를 함께 처리한다.",
            shape="브라우저 → Node(실시간+요약 워커) → PostgreSQL",
            data_flow="전송 → DB 기록 → 룸 브로드캐스트",
            build_order=["메시지 스키마", "실시간 전달"],
            open_questions=["사내 SSO 프로토콜 미확인"],
        ),
        runs_dir=runs_dir,
    )
    store.upsert_final_design(
        SLUG,
        FinalDesign(
            summary="socket.io로 실시간 전달을 얹고 메시지는 PostgreSQL에 저장한다.",
            shape="브라우저 → Node(실시간) → PostgreSQL · 요약 워커 별 프로세스",
            data_flow="전송 → DB 기록 → 룸 브로드캐스트 → 워커가 요약",
            changes_from_design=[
                "요약 워커를 백엔드 프로세스에서 분리했다 — socket.io 판정의 caveats"
            ],
            stack_rationale="세 선택이 모두 운영 컴포넌트를 늘리지 않는 제약에서 나왔다",
            integration_notes=["룸 이름과 채널 ID를 같은 값으로 쓴다"],
            combination_risks=["단일 프로세스 전제가 깨지면 어댑터가 필요해진다"],
            build_order=["메시지 스키마", "socket.io 룸 전달", "요약 워커"],
            unresolved=["인증: priority가 밀려 이번 실행에서 다루지 않음"],
        ),
        runs_dir=runs_dir,
    )


def test_final_design_is_rendered_at_the_top(runs_dir: str):
    _seed_basic(runs_dir)
    _seed_designs(runs_dir)

    ctx = build_report_context(SLUG, runs_dir=runs_dir)
    html = render_report(ctx)

    assert ctx["final_design"] is not None
    # 확정 설계의 본문은 구조다 — 없으면 "수정 설계 완성"이 성립하지 않는다
    assert "요약 워커 별 프로세스" in html
    assert "워커가 요약" in html
    assert "요약 워커를 백엔드 프로세스에서 분리했다" in html
    assert "룸 이름과 채널 ID를 같은 값으로 쓴다" in html
    assert "단일 프로세스 전제가 깨지면" in html
    assert "인증: priority가 밀려" in html
    # 권장 설계가 확정 스택보다 먼저 나온다
    assert html.index("권장 설계") < html.index("확정 스택")


def test_v1_is_kept_for_contrast(runs_dir: str):
    """designs(v1)가 덮어써지지 않아야 대조가 성립한다 — 같은 필드를 나란히 놓는다."""
    _seed_basic(runs_dir)
    _seed_designs(runs_dir)

    ctx = build_report_context(SLUG, runs_dir=runs_dir)
    html = render_report(ctx)

    assert ctx["architecture"] is not None
    assert ctx["architecture"].shape != ctx["final_design"].shape
    assert "Node(실시간+요약 워커)" in html, "기본틀의 구조가 대조에 안 나온다"
    assert "사내 SSO 프로토콜 미확인" in html


def test_unchanged_design_says_so_instead_of_hiding(runs_dir: str):
    """changes_from_design이 비면 지우지 않는다 — 기본틀이 조사를 견뎠다는 정보다."""
    _seed_basic(runs_dir)
    _seed_designs(runs_dir)
    final = store.get_final_design(SLUG, runs_dir=runs_dir)
    store.upsert_final_design(
        SLUG, final.model_copy(update={"changes_from_design": []}), runs_dir=runs_dir
    )

    html = render_report(build_report_context(SLUG, runs_dir=runs_dir))

    assert "조사 결과가 기본틀을 바꾸지 않았습니다" in html


def test_missing_final_design_shows_reason_not_blank(runs_dir: str):
    _seed_basic(runs_dir)  # designs·final_designs 없음

    ctx = build_report_context(SLUG, runs_dir=runs_dir)
    html = render_report(ctx)

    assert ctx["final_design"] is None
    assert "권장 설계" in html, "행이 없다고 섹션을 지우면 안 된다"
    assert "설계 확정이 실패했거나" in html
    assert "설계 본문이 저장되지 않았습니다" in html


def test_closed_decisions_are_separate_from_deferred(runs_dir: str):
    """"필요 없어서"와 "이미 정해져서"는 다른 섹션이다 (불변식 17)."""
    _seed_basic(runs_dir)
    components = store.get_components(SLUG, runs_dir=runs_dir)
    components.append(
        Component(
            name="서버 런타임·언어",
            kind="infrastructure",
            role_in_design="실행 환경",
            decision_question="런타임은 무엇인가",
            needs_comparison=False,
            no_comparison_reason="3인 TypeScript 팀 — 이미 닫힌 결정",
            necessity="essential",
            necessity_reason="없으면 실행이 안 된다",
            priority=2,
            approach_notes="",
        )
    )
    store.upsert_components(SLUG, components, runs_dir=runs_dir)

    ctx = build_report_context(SLUG, runs_dir=runs_dir)
    html = render_report(ctx)

    assert [c.name for c in ctx["closed"]] == ["서버 런타임·언어"]
    assert "3인 TypeScript 팀 — 이미 닫힌 결정" in html
    # 닫힌 결정은 "지금 만들지 않아도 되는 것"에 중복으로 나오지 않는다
    assert all(c.name != "서버 런타임·언어" for c in ctx["deferred"])
    # search로 넘기는 집합에서도 빠진다
    assert "서버 런타임·언어" not in [c.name for c in ctx["skipped"]]


def test_report_uses_no_llm(runs_dir: str):
    """불변식 7 — 이 단계에서 새 주장이 생길 수 없다."""
    source = Path("packages/scout/src/scout/stages/report.py").read_text(
        encoding="utf-8"
    )

    assert "invoke" not in source
    assert "make_llm" not in source
