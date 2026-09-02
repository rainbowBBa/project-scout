import operator
from typing import Annotated, TypedDict

from scout.schemas import Candidate, Component, ElementPick, Interview, Verdict


class ScoutState(TypedDict, total=False):
    slug: str
    description: str
    max_components: int
    max_candidates: int
    interview: Interview
    components: list[Component]
    # candidates/verdicts/element_picks는 요소별·후보별 Send fan-out으로 채워진다 —
    # operator.add로 병렬 브랜치의 결과를 리스트 이어붙이기로 리듀스한다 (graph.py, STEP 03~).
    candidates: Annotated[list[Candidate], operator.add]
    verdicts: Annotated[list[Verdict], operator.add]
    element_picks: Annotated[list[ElementPick], operator.add]
