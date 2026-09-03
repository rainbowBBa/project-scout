"""재실행이 상태를 누적하지 않는지 검사한다 — LLM도 네트워크도 쓰지 않는다.

검증하는 주장: **같은 slug로 다시 돌려도 판정·후보가 중복되지 않는다.**

`candidates`·`verdicts`·`element_picks`에 `operator.add` 리듀서가 붙어 있었다.
리듀스할 `Send` fan-out이 없는데(병렬은 노드 내부의 `asyncio.gather`다) 남아 있어서,
같은 `thread_id`로 재실행하면 체크포인터가 복원한 이전 상태에 **누적**됐다 —
`판정 6개`인데 DB는 3행이었고, `evaluate`가 중복 목록을 채점해 순위가
`socket.io > socket.io > …`로 나왔다.

리듀서가 조용히 돌아오면 같은 일이 생기는데 화면만 보고는 알기 어렵다. 그래서 스텁
노드로 실제 그래프를 두 번 돌려 길이를 본다.
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from scout.state import ScoutState

_ACCUMULATING = ("candidates", "verdicts", "element_picks")


def _run_twice(field: str) -> tuple[int, int]:
    """노드가 매번 같은 2개짜리 리스트를 반환한다. 같은 thread_id로 두 번 돌린다."""

    def node(_state: ScoutState) -> dict:
        return {field: ["a", "b"]}

    graph = StateGraph(ScoutState)
    graph.add_node("only", node)
    graph.add_edge(START, "only")
    graph.add_edge("only", END)
    app = graph.compile(checkpointer=InMemorySaver())

    config = {"configurable": {"thread_id": "same-slug"}}
    first = app.invoke({"slug": "same-slug"}, config=config)
    second = app.invoke({"slug": "same-slug"}, config=config)
    return len(first[field]), len(second[field])


def test_rerun_does_not_accumulate():
    """★ 재실행이 리스트를 두 배로 만들지 않는다."""
    for field in _ACCUMULATING:
        first, second = _run_twice(field)

        assert first == 2, f"{field}: 첫 실행이 2개가 아니다 ({first})"
        assert second == 2, (
            f"{field}: 재실행에서 {second}개로 늘었다 — 리듀서가 돌아왔다. "
            "판정·순위에 이전 실행의 항목이 중복으로 섞인다"
        )


def test_no_reducer_annotations_on_list_fields():
    """리듀서를 되돌리면 위 테스트가 잡지만, 왜 없는지도 함께 고정한다.

    `Send` fan-out을 도입하면 이 단언을 의도적으로 고쳐야 한다 — 그때는 `cli.py`의
    스트림 루프도 함께 고쳐야 한다는 신호다 (state.py 참고).
    """
    hints = ScoutState.__annotations__

    for field in _ACCUMULATING:
        assert getattr(hints[field], "__metadata__", None) is None, (
            f"{field}에 리듀서가 붙었다 — Send fan-out을 정말 도입했는지 확인하고, "
            "그렇다면 cli.py의 스트림 루프도 함께 고쳤는지 본다"
        )
