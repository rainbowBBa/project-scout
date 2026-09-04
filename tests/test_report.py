"""report 단계 — scout.db를 읽어 조립한 컨텍스트와 렌더링 결과를 검사한다.

LLM도 네트워크도 쓰지 않는 단계라 store에 손으로 시드하고 결과만 본다
(stages/5-report.md 완료 기준).
"""

import re
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
from scout.stages.report import (
    build_report_context,
    render_report,
    split_sentences,
)

SLUG = "test-run"

# 섹션 제목과 목차 링크가 같은 문자열이라 이름으로 자르면 목차를 잡는다 — 앵커로 가른다
_ANCHORS = (
    "recommended", "picked", "closed", "deferred", "skipped",
    "baseline", "compared", "rejected", "facts", "commands",
)


def _sections(html: str) -> dict[str, str]:
    """앵커 id로 섹션 본문을 가른다."""
    marks = sorted((html.index(f'id="{a}"'), a) for a in _ANCHORS)
    out = {}
    for i, (pos, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(html)
        out[name] = html[pos:end]
    return out




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
    # 막대 바로 아래에 점수 근거가 붙는다. "선택한 기술" 표는 근거를 접으므로
    # (표 높이가 화면을 덮었다) 이 단언은 매크로가 근거를 그대로 붙이는 곳을 본다
    compared = _sections(html)["compared"]
    idx_bar = compared.index('style="width: 80%"')  # overall=4 → 80%
    idx_reason = compared.index("제약상 재연결 내장이 중요", idx_bar)
    assert idx_reason - idx_bar < 400
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
    # 최상단이 권장 설계라는 계약 (STEP 11)
    assert html.index('id="recommended"') < html.index('id="picked"')


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


# ── 가독성 — 제목 · 문장 끊기 · 중복 접기 (001 v30) ─────────────────────

# 실측된 실패: judge가 쓴 문장이 한 문단 630자였고, 저장된 값에 줄바꿈이 하나도 없어서
# 화면이 글자 벽이 됐다. 아래 셋이 그 상태로 돌아가는 것을 막는다.


def test_sentences_splits_korean_prose():
    """★ 문장 경계에서만 끊는다 — 문장을 고치거나 줄이지 않는다."""
    text = "첫 문장이다. 둘째 문장이다. 셋째 문장이다."

    assert split_sentences(text) == ["첫 문장이다.", "둘째 문장이다.", "셋째 문장이다."]


def test_sentences_does_not_break_versions_or_money():
    """버전·금액에서 끊기면 사실이 두 조각으로 갈린다."""
    text = "pypi.latest_version 4.17.11로 확인됐다. 월 예산은 $200.00이다."

    parts = split_sentences(text)

    assert len(parts) == 2, parts
    assert "4.17.11" in parts[0]
    assert "$200.00" in parts[1]


def test_sentences_honors_newlines_if_the_model_supplies_them():
    """지금 LLM은 줄바꿈을 안 주지만, 오면 문단 경계로 존중한다."""
    assert split_sentences("위쪽\n\n아래쪽") == ["위쪽", "아래쪽"]


def test_long_prose_is_rendered_as_paragraphs(runs_dir: str):
    """★ 630자 한 문단이 화면에서 문단으로 끊긴다.

    `<p>` 개수를 세는 것이 검사 대상이다 — 문자열이 남아 있는지만 보면 통째로 찍혀도
    통과한다.
    """
    _seed_basic(runs_dir)
    _seed_designs(runs_dir)
    final = store.get_final_design(SLUG, runs_dir=runs_dir)
    store.upsert_final_design(
        SLUG,
        final.model_copy(
            update={
                "stack_rationale": "첫 근거다. 둘째 근거다. 셋째 근거다. 넷째 근거다."
            }
        ),
        runs_dir=runs_dir,
    )

    html = render_report(build_report_context(SLUG, runs_dir=runs_dir))

    block = html[html.index("왜 이 조합인가") : html.index("구축 순서")]
    assert block.count("<p>") == 4, "긴 산문이 한 덩어리로 찍혔다"
    assert "넷째 근거다." in block, "문장이 사라졌다 — 끊기만 해야 한다"


def test_title_comes_from_interview_not_the_raw_question(runs_dir: str):
    """★ 제목은 사용자가 타이핑한 질문이 아니다 (불변식 7 — interview가 쓴다)."""
    _seed_basic(runs_dir)
    run = store.get_run(SLUG, runs_dir=runs_dir)
    interview = Interview.model_validate(run["interview"]).model_copy(
        update={
            "title": "사내 AI 요약 팀 채팅 앱",
            "constraints": ["사내 200명", "3인 TypeScript", "월 $200"],
        }
    )
    store.upsert_run(
        SLUG, run["description"], run["created_at"], interview, runs_dir=runs_dir
    )

    ctx = build_report_context(SLUG, runs_dir=runs_dir)
    html = render_report(ctx)

    assert ctx["title"] == "사내 AI 요약 팀 채팅 앱"
    assert html.index("사내 AI 요약 팀 채팅 앱") < html.index('id="recommended"')
    for chip in ("사내 200명", "3인 TypeScript", "월 $200"):
        assert chip in html
    # refined_brief 전문은 제목 밑이 아니라 본문에 있다
    assert html.index("구체화된 명세") > html.index('id="recommended"')


def test_title_falls_back_for_older_runs(runs_dir: str):
    """예전 실행의 interview_json에는 title이 없다 — report는 LLM 없이 다시 렌더링된다."""
    _seed_basic(runs_dir)

    ctx = build_report_context(SLUG, runs_dir=runs_dir)

    assert ctx["title"] == "사내 200명 팀 채팅 앱"  # description으로 물러났다
    assert ctx["constraints"] == []


def test_overlong_title_falls_back(runs_dir: str):
    """모델이 제목 자리에 문단을 넣으면 h1이 세 줄이 된다 — 그때는 원문이 낫다."""
    _seed_basic(runs_dir)
    run = store.get_run(SLUG, runs_dir=runs_dir)
    interview = Interview.model_validate(run["interview"]).model_copy(
        update={"title": "가" * 61}
    )
    store.upsert_run(
        SLUG, run["description"], run["created_at"], interview, runs_dir=runs_dir
    )

    assert build_report_context(SLUG, runs_dir=runs_dir)["title"] == run["description"]


def test_winner_reason_is_not_printed_twice_in_full(runs_dir: str):
    """★ 같은 문장을 두 번 읽지 않는다 — 둘째 출현은 첫 문장만 보이고 접힌다.

    실측에서 563자 `winner_reason`이 "선택한 기술" 표와 "결정 지점별 비교"에 각각
    전문으로 찍혀 체감 분량이 2배였다.
    """
    _seed_basic(runs_dir)
    store.clear_picks(SLUG, "실시간 메시지 전달", runs_dir=runs_dir)
    store.add_pick(
        SLUG,
        "실시간 메시지 전달",
        "socket.io",
        rank=1,
        winner_reason="첫 문장은 결론이다. 둘째 문장은 근거다.",
        runner_up_note="ws도 합리적 선택지다",
        margin="close",
        runs_dir=runs_dir,
    )

    html = render_report(build_report_context(SLUG, runs_dir=runs_dir))
    sections = _sections(html)
    table, compared = sections["picked"], sections["compared"]

    # 전문은 표에만 있다
    assert "둘째 문장은 근거다." in table
    # 비교 섹션은 첫 문장만 펼쳐 보인다 — 나머지는 <summary> 뒤(접힌 본문)에 있다
    summary = compared[
        compared.index("<summary><strong>1위</strong>") : compared.index("</summary>")
    ]
    assert "첫 문장은 결론이다." in summary
    assert "둘째 문장은 근거다." not in summary, "접히지 않고 전문이 두 번 찍혔다"
    assert "둘째 문장은 근거다." in compared, "접었다고 지우면 안 된다 (불변식 12)"


def test_judge_verdict_is_visible(runs_dir: str):
    """점수만 보이면 무엇을 고른 건지 알 수 없다 — 컨텍스트엔 있었는데 화면에 없었다."""
    _seed_basic(runs_dir)

    html = render_report(build_report_context(SLUG, runs_dir=runs_dir))

    block = _sections(html)["compared"]
    assert "재연결·룸을 내장한 실시간 통신 라이브러리" in block  # what_it_is
    assert "재연결·룸을 내장해 요구를 직접 충족" in block  # solves_reason
    assert "재연결 자동" in block  # pros


def test_screen_labels_are_korean(runs_dir: str):
    """화면에 보이는 라벨에 영어를 남기지 않는다 (CSS 클래스명은 그대로다)."""
    _seed_basic(runs_dir)

    html = render_report(build_report_context(SLUG, runs_dir=runs_dir))

    assert ">계산<" in html and ">판정<" in html
    for leftover in ("gaps:", ">link<", "confidence:", "<th>fact_id</th>"):
        assert leftover not in html, f"화면에 영어가 남았다: {leftover}"


def test_stack_table_folds_its_prose(runs_dir: str):
    """선택한 기술 표는 막대만 펼쳐 두고 산문을 접는다.

    실측에서 선정 이유 426자 · 점수 근거 276자가 한 행에 그대로 들어가 표 한 행이
    화면을 덮었다. 막대는 남긴다 — 비교가 한눈에 보이는 것이 이 표의 목적이다.
    """
    _seed_basic(runs_dir)

    html = render_report(build_report_context(SLUG, runs_dir=runs_dir))
    table = _sections(html)["picked"]

    assert 'style="width: 80%"' in table, "막대가 사라졌다 — 비교가 안 보인다"
    assert '<details class="folded">' in table, "산문이 접히지 않았다"
    # 선정 이유와 점수 근거가 같은 접힌 물 안에 있다
    assert table.count('<details class="folded">') == 1
    assert "점수 근거" in table
    # 접었다고 지우지 않는다 (불변식 12)
    assert "제약상 재연결 내장이 중요" in table


def test_next_command_hints_name_real_stages(runs_dir: str):
    """리포트가 찍는 명령은 붙여넣으면 돌아가야 한다 (001/09-출력양식.md).

    `analyze`가 `design`으로 바뀐 뒤에도 이 힌트가 남아 실패하는 명령을 찍고 있었다.
    """
    from scout.cli import ShowStage

    _seed_basic(runs_dir)
    html = render_report(build_report_context(SLUG, runs_dir=runs_dir))

    hints = _sections(html)["commands"]
    stages = {s.value for s in ShowStage}
    for token in re.findall(r"scout show \S+ (\w+)", hints):
        assert token in stages, f"'{token}'은 scout show가 받지 않는 단계다"


# ── 양식: 그룹 · 목차 · 팝오버 (001 v33) ────────────────────────────────


def test_sections_are_grouped_by_role(runs_dir: str):
    """★ 섹션 10개가 결론·전제·근거로 갈린다.

    전부 같은 무게로 나열되면 읽는 사람이 어디까지 읽어야 하는지 알 수 없다.
    """
    _seed_basic(runs_dir)
    _seed_designs(runs_dir)

    html = render_report(build_report_context(SLUG, runs_dir=runs_dir))

    for label in ("결론", "전제", "근거"):
        assert f'class="group-label">{label}<' in html, f"'{label}' 그룹이 없다"

    # 결론에 권장 설계·선택한 기술, 근거에 수집한 사실이 들어간다
    conclusion = html[html.index("group-conclusion") : html.index("group-premise")]
    evidence = html[html.index("group-evidence") :]
    assert 'id="recommended"' in conclusion and 'id="picked"' in conclusion
    assert 'id="facts"' in evidence and 'id="compared"' in evidence
    # v1 대조는 결론이 아니라 전제다 — 결론과 섞이면 무게가 뭉개진다
    assert 'id="baseline"' not in conclusion


def test_toc_anchors_point_at_real_sections(runs_dir: str):
    """★ 깨진 앵커는 화면에 안 보이는 실패다 — 클릭해도 아무 일이 안 일어난다."""
    _seed_basic(runs_dir)

    html = render_report(build_report_context(SLUG, runs_dir=runs_dir))

    targets = re.findall(r'<a href="#([\w-]+)"', html)
    assert targets, "목차가 렌더링되지 않았다"
    for target in targets:
        assert f'id="{target}"' in html, f"#{target} 앵커의 대상이 없다"


def test_popovers_open_on_focus_not_only_hover(runs_dir: str):
    """★ 터치 기기에는 호버가 없다 — 포커스로도 열려야 그 설명이 존재하는 것이다."""
    _seed_basic(runs_dir)

    html = render_report(build_report_context(SLUG, runs_dir=runs_dir))

    assert 'class="hint-body"' in html, "보조 설명 팝오버가 없다"
    assert ".hint:focus-within > .hint-body" in html
    assert 'tabindex="0"' in html, "키보드로 닿을 수 없다"
    # 배지가 뜻을 갖는다 — 모르면 배지가 장식이 된다
    assert "rubric.py의 공식이 사실에서 계산한 값이다" in html


def test_popovers_do_not_widen_the_page_on_narrow_screens(runs_dir: str):
    """★ absolute 팝오버는 숨겨진 상태로도 폭을 차지한다 — 420px 실측에서 페이지가
    179px 가로 스크롤됐다. fixed는 scrollWidth에 기여하지 않는다."""
    _seed_basic(runs_dir)

    html = render_report(build_report_context(SLUG, runs_dir=runs_dir))

    at = html.find("@media (max-width: 640px)")
    assert at != -1, "좁은 화면용 팝오버 규칙이 없다"
    block = html[at : html.index("\n  }", at)]
    assert ".hint-body" in block and "position: fixed" in block, (
        "좁은 화면에서 팝오버가 absolute로 남으면 리포트가 가로로 스크롤된다"
    )


def test_print_reveals_folded_content(runs_dir: str):
    """공유가 이 문서의 목적이다 — 인쇄에서 접힌 내용이 사라지면 안 된다."""
    _seed_basic(runs_dir)

    html = render_report(build_report_context(SLUG, runs_dir=runs_dir))

    assert "@media print" in html
    assert "details:not([open]) > *:not(summary) { display: block; }" in html
    assert "nav.toc, .hint-body { display: none; }" in html


def test_toc_and_popovers_use_no_javascript(runs_dir: str):
    """목차·팝오버를 CSS로만 만들었다는 증거 — 자체 완결 단일 파일이어야 한다."""
    _seed_basic(runs_dir)

    html = render_report(build_report_context(SLUG, runs_dir=runs_dir))

    assert "<script" not in html
    assert "cdn." not in html
    assert "onclick" not in html and "onmouseover" not in html
