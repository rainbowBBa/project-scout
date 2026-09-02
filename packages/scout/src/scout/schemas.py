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


class Component(BaseModel):
    name: str
    kind: Literal["feature", "data", "infrastructure", "integration", "ops"]
    why: str
    necessity: Literal["essential", "valuable", "defer", "unnecessary"]
    necessity_reason: str
    priority: int
    approach_notes: str
    # search 단계에 상태로만 넘긴다 — components 테이블에는 저장하지 않는다 (1-analyze.md)
    search_hints: list[str] = Field(default_factory=list)


class Analysis(BaseModel):
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
