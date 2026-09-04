from typing import TypedDict

from scout.schemas import (
    Architecture,
    Candidate,
    Component,
    ElementPick,
    FinalDesign,
    Interview,
    Verdict,
)


class ScoutState(TypedDict, total=False):
    """LangGraph 상태. 리듀서(`Annotated[..., operator.add]`)를 쓰지 않는다.

    `Send` fan-out을 쓰지 않으므로 리듀스할 것이 없다 — 병렬은 노드 내부의
    `asyncio.gather`로 하고 각 필드는 노드가 전체 리스트를 한 번에 반환한다
    (001/stages/2-search.md "동시성").

    리듀서를 붙이면 같은 `thread_id`(= slug)로 재실행할 때 체크포인터가 복원한 이전
    상태에 누적돼 판정·순위가 중복된다. `Send`를 도입하면 그 필드에만 다시 붙이고
    `cli.py`의 스트림 루프도 함께 고쳐야 한다.
    """

    slug: str
    description: str
    max_components: int
    max_candidates: int
    max_turns: int
    interview: Interview
    architecture: Architecture
    components: list[Component]
    candidates: list[Candidate]
    verdicts: list[Verdict]
    element_picks: list[ElementPick]
    final_design: FinalDesign
    report_path: str
    report_summary: dict
