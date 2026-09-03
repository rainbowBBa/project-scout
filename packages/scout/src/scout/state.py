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
    """LangGraph 상태. **리듀서(`Annotated[..., operator.add]`)를 쓰지 않는다.**

    ★ `candidates`·`verdicts`·`element_picks`에 `operator.add`가 붙어 있었는데,
    리듀스할 fan-out이 없었다. `Send` API는 이 프로젝트에서 쓰지 않는다 — 한 superstep에
    여러 노드 키가 올라와 `cli.py`의 스트림 루프(첫 키만 읽는다)와 단계 배너가 깨지기
    때문이다 (001/stages/2-search.md "동시성"). 병렬은 **노드 내부의 `asyncio.gather`**로
    하고, 각 필드는 노드 하나가 전체 리스트를 한 번에 반환한다.

    남아 있던 리듀서의 유일한 효과는 버그였다 — 같은 `thread_id`(= slug)로 재실행하면
    체크포인터가 이전 상태를 복원하고 `operator.add`가 **누적**해서, 판정·순위에 이전
    실행의 항목이 중복으로 섞였다(`판정 6개`인데 DB는 3행). 기본 채널(LastValue)이면
    노드가 반환한 값이 교체하므로 재실행이 깨끗하다.

    나중에 `Send` fan-out을 도입하면 그 필드에만 리듀서를 다시 붙여야 한다 —
    그때는 `cli.py`의 스트림 루프도 함께 고쳐야 한다.
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
