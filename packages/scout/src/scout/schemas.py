import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field

# 의사 XML 태그. `>`로 닫히는 것만 잡으므로 "a < b" 같은 평문은 건드리지 않는다.
_TAG_RE = re.compile(r"<[^<>]{1,120}>")


def _as_list(value: Any) -> Any:
    """리스트 자리에 온 문자열을 흡수한다 — 태그를 항목 구분자로 보고 쪼갠다.

    실측: Bedrock tool-use가 JSON 배열 대신 의사 XML을 흘려보낸다. 두 형태를 봤다.

        "<item>자동 재연결</item><item>룸 내장</item>"
        '<parameter name="pro">자동 재연결…<parameter name="pro">룸 내장…'   (Haiku)

    그냥 실패로 두면 `Verdict` 파싱이 깨져 **그 후보가 탈락 처리되고** dossier도
    판정도 남지 않는다 — 형식 흔들림 하나가 조사 결과를 지운다. 태그를 남겨두면
    그 문자열이 그대로 보고서에 찍힌다. 판단을 바꾸는 게 아니라 형식만 맞추는 자리다.
    """
    if not isinstance(value, str):
        return value
    return [part for part in (p.strip() for p in _TAG_RE.split(value)) if part]


# list[str] 필드는 전부 이 타입을 쓴다 — 어느 스키마에서 흔들릴지 미리 알 수 없다.
StrList = Annotated[list[str], BeforeValidator(_as_list)]


class Interview(BaseModel):
    raw_description: str
    refined_brief: str
    assumptions: StrList


class InterviewTurn(BaseModel):
    """대화 루프 전용 판단 — 저장되지 않는다 (0-interview.md)."""

    done: bool
    question: str | None = None


class Architecture(BaseModel):
    """기본틀(v1). evaluate가 조사 결과로 수정해 FinalDesign으로 확정한다 (1-design.md)."""

    summary: str
    shape: str
    data_flow: str
    build_order: StrList = Field(default_factory=list)
    open_questions: StrList = Field(default_factory=list)


class Component(BaseModel):
    """설계의 구성 단위이면서 **비교해서 정해야 할 결정 지점** (1-design.md)."""

    name: str
    kind: Literal["feature", "data", "infrastructure", "integration", "ops"]
    role_in_design: str
    decision_question: str
    constraints: StrList = Field(default_factory=list)
    # necessity("필요한가")와 다른 축이다 — "지금 비교해서 골라야 하는가".
    # false면 설계에서 이미 닫힌 결정이라 search에 가지 않는다 (불변식 17)
    needs_comparison: bool = True
    no_comparison_reason: str = ""
    necessity: Literal["essential", "valuable", "defer", "unnecessary"]
    necessity_reason: str
    priority: int
    approach_notes: str
    # 영어 기술 어휘. 비면 search가 한국어 추상어로 npm_search를 부르게 된다 (불변식 16)
    search_hints: StrList = Field(default_factory=list)


class Design(BaseModel):
    architecture: Architecture
    components: list[Component]


class Fact(BaseModel):
    id: str
    label: str
    value: str
    url: str | None
    retrieved_at: str


class Candidate(BaseModel):
    component: str
    name: str
    kind: Literal["method", "software", "library"]
    what_it_is: str
    dossier: list[Fact] = Field(default_factory=list)
    dossier_gaps: StrList = Field(default_factory=list)


class CandidateDraft(BaseModel):
    """에이전트가 뽑는 후보. dossier는 코드가 ToolMessage에서 채운다 — LLM이 쓴 문장에서
    사실을 만들면 judge가 인용할 dossier 자체가 LLM 생성물이 된다 (불변식 4).
    """

    name: str
    kind: Literal["method", "software", "library"]
    what_it_is: str


class CandidateList(BaseModel):
    candidates: list[CandidateDraft]


class Verdict(BaseModel):
    candidate: str
    component: str
    solves_it: bool
    solves_reason: str
    pros: StrList
    cons: StrList
    caveats: StrList
    confidence: Literal["high", "medium", "low"]
    citations: StrList
    unsupported_claims: StrList = Field(default_factory=list)


class CandidateScore(BaseModel):
    candidate: str
    overall: int
    score_reason: str


class ElementPick(BaseModel):
    component: str
    scores: list[CandidateScore]
    ranking: StrList
    winner: str
    winner_reason: str
    runner_up_note: str
    margin: Literal["decisive", "close"]


class FinalDesign(BaseModel):
    """`Architecture`(v1)를 조사 결과로 수정한 확정 설계(v2) — 별개 문서가 아니다.

    `shape`·`data_flow`가 `Architecture`와 **같은 이름**인 것은 의도다. 그래야 v1↔v2
    대조가 필드 단위로 성립하고, `report`가 LLM 없이 나란히 놓기만 해도 대조표가 된다
    (4-evaluate.md "확정 설계는 기본틀의 수정판이다").
    """

    summary: str
    shape: str
    data_flow: str
    # 무엇이 · 왜 · 무엇을 근거로 바뀌었나. 비면 "기본틀 유지"다 — 지우지 않는다(불변식 12)
    changes_from_design: StrList = Field(default_factory=list)
    stack_rationale: str
    integration_notes: StrList = Field(default_factory=list)
    # 조합해서 비로소 생기는 위험만. verdicts.cons의 사본이면 실패다
    combination_risks: StrList = Field(default_factory=list)
    build_order: StrList = Field(default_factory=list)
    unresolved: StrList = Field(default_factory=list)
