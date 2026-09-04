"""winner_reason의 첫머리가 결정 지점마다 달라야 한다 — LLM도 네트워크도 쓰지 않는다.

검증하는 주장: **보고서 표에서 행이 구분된다.** 표는 첫 문장만 잘라서 보여주므로
(5-report.md), 첫머리가 같으면 표가 정보를 잃는다. 프롬프트 지시와 코드 검출을
함께 본다.
"""

from scout.prompts import EVALUATE_SYSTEM_PROMPT
from scout.schemas import CandidateScore, ElementPick, Verdict
from scout.stages.evaluate import audit_headlines, solo_pick


def _pick(component: str, winner_reason: str, *, scored: bool = True) -> ElementPick:
    return ElementPick(
        component=component,
        scores=[CandidateScore(candidate="a", overall=5, score_reason="근거")]
        if scored
        else [],
        ranking=["a"],
        winner="a",
        winner_reason=winner_reason,
        runner_up_note="2위는 없다",
        margin="decisive",
    )


def test_identical_openings_are_recorded_as_a_gap():
    picks = [
        _pick("프론트엔드 프로토타이핑 프레임워크", "1인 개발자가 1~2주 내 데모 완성이라는 제약에서 Gradio의 …"),
        _pick("LangChain 모델 래퍼 구현 방식", "1인 개발자가 1~2주 내 데모 완성이라는 제약에서 @langchain/core는 …"),
        _pick("HTTP 클라이언트 라이브러리", "requests는 54,277 스타로 검증됐다. overall 5 대 3."),
    ]

    gaps = audit_headlines(picks)

    assert len(gaps) == 1, f"첫머리 중복을 못 잡았다: {gaps}"
    assert "프론트엔드 프로토타이핑 프레임워크" in gaps[0]
    assert "LangChain 모델 래퍼 구현 방식" in gaps[0]
    assert "HTTP 클라이언트 라이브러리" not in gaps[0], "다르게 시작한 행까지 걸었다"


def test_distinct_openings_pass():
    picks = [
        _pick("프론트엔드", "gh.issue_close_rate 0.98로 Streamlit(0.81)보다 빠르다. overall 5 대 4."),
        _pick("래퍼", "BaseChatModel 추상 클래스를 직접 제공한다. overall 5 대 3."),
        _pick("HTTP", "requests는 54,277 스타로 검증됐다. overall 5 대 3."),
    ]

    assert audit_headlines(picks) == []


def test_solo_picks_are_not_flagged():
    """고정 문구라 중복이 정상이다."""
    verdict = Verdict(
        candidate="a",
        component="c",
        solves_it=True,
        solves_reason="요구를 충족",
        pros=[],
        cons=[],
        caveats=[],
        confidence="high",
        citations=[],
    )
    picks = [solo_pick("요소1", verdict), solo_pick("요소2", verdict)]

    assert picks[0].winner_reason == picks[1].winner_reason  # 전제 확인
    assert audit_headlines(picks) == []


def test_prompt_forbids_opening_with_the_brief():
    assert "첫 문장은 **이 후보만의 것**으로 시작한다" in EVALUATE_SYSTEM_PROMPT
    assert "문장을 그것으로 시작하지 않는다" in EVALUATE_SYSTEM_PROMPT
    assert "refined_brief 의 문장을 옮겨 적지 않는다" in EVALUATE_SYSTEM_PROMPT
    assert "overall 점수 차이는 숫자로 쓴다" in EVALUATE_SYSTEM_PROMPT
