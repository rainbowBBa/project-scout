from typing import Literal

from pydantic import BaseModel, Field


class Interview(BaseModel):
    raw_description: str
    refined_brief: str
    assumptions: list[str]


class InterviewTurn(BaseModel):
    """대화 루프 전용 판단 — 저장되지 않는다 (0-interview.md)."""

    done: bool
    question: str | None = None


class Architecture(BaseModel):
    """기본틀(v1). evaluate가 조사 결과로 수정해 FinalDesign으로 확정한다 (1-design.md)."""

    summary: str
    shape: str
    data_flow: str
    build_order: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class Component(BaseModel):
    """설계의 구성 단위이면서 **비교해서 정해야 할 결정 지점** (1-design.md)."""

    name: str
    kind: Literal["feature", "data", "infrastructure", "integration", "ops"]
    role_in_design: str
    decision_question: str
    constraints: list[str] = Field(default_factory=list)
    # necessity("필요한가")와 다른 축이다 — "지금 비교해서 골라야 하는가".
    # false면 설계에서 이미 닫힌 결정이라 search에 가지 않는다 (불변식 17)
    needs_comparison: bool = True
    no_comparison_reason: str = ""
    necessity: Literal["essential", "valuable", "defer", "unnecessary"]
    necessity_reason: str
    priority: int
    approach_notes: str
    # 영어 기술 어휘. 비면 search가 한국어 추상어로 npm_search를 부르게 된다 (불변식 16)
    search_hints: list[str] = Field(default_factory=list)


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
    dossier_gaps: list[str] = Field(default_factory=list)


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
    pros: list[str]
    cons: list[str]
    caveats: list[str]
    confidence: Literal["high", "medium", "low"]
    citations: list[str]
    unsupported_claims: list[str] = Field(default_factory=list)


class CandidateScore(BaseModel):
    candidate: str
    overall: int
    score_reason: str


class ElementPick(BaseModel):
    component: str
    scores: list[CandidateScore]
    ranking: list[str]
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
    changes_from_design: list[str] = Field(default_factory=list)
    stack_rationale: str
    integration_notes: list[str] = Field(default_factory=list)
    # 조합해서 비로소 생기는 위험만. verdicts.cons의 사본이면 실패다
    combination_risks: list[str] = Field(default_factory=list)
    build_order: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
