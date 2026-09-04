"""StateGraph 골격. 6단계 노드가 순서대로 이어진다.

thread_id = slug 로 SqliteSaver 체크포인터를 물려서, 같은 slug로 다시 실행하면
LangGraph가 끝난 노드를 건너뛰고 이어서 돈다 (02-파이프라인.md "재개").
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

from scout.approval import default_approve
from scout.stages import design as design_stage
from scout.stages import evaluate as evaluate_stage
from scout.stages import interview as interview_stage
from scout.stages import report as report_stage
from scout.stages import search as search_stage
from scout.stages import verify as verify_stage
from scout.state import ScoutState

if TYPE_CHECKING:
    from langchain_aws import ChatBedrockConverse
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from scout.approval import Approve


def build_graph(
    llm: ChatBedrockConverse,
    checkpointer: BaseCheckpointSaver,
    *,
    approve: Approve = default_approve,
):
    graph = StateGraph(ScoutState)
    graph.add_node(
        "interview", lambda state: interview_stage.interview_node(state, llm=llm)
    )
    graph.add_node(
        "design",
        lambda state: design_stage.design_node(state, llm=llm, approve=approve),
    )
    graph.add_node(
        "search",
        lambda state: search_stage.search_node(state, llm=llm, approve=approve),
    )
    graph.add_node("verify", lambda state: verify_stage.verify_node(state, llm=llm))
    graph.add_node(
        "evaluate", lambda state: evaluate_stage.evaluate_node(state, llm=llm)
    )
    graph.add_node("report", lambda state: report_stage.report_node(state))
    graph.add_edge(START, "interview")
    graph.add_edge("interview", "design")
    graph.add_edge("design", "search")
    graph.add_edge("search", "verify")
    graph.add_edge("verify", "evaluate")
    graph.add_edge("evaluate", "report")
    graph.add_edge("report", END)
    return graph.compile(checkpointer=checkpointer)


def make_slug(description: str, *, today: str) -> str:
    """`<YYYYMMDD>-<설명 해시 8자>`. 폴더명이자 체크포인터 `thread_id`다.

    설명만의 함수여야 한다 — 같은 날 같은 설명으로 다시 실행하면 같은 slug가 나와
    체크포인터가 끝난 단계를 건너뛴다. `hash()`는 프로세스마다 랜덤이라 못 쓴다.

    설명에서 단어를 뽑아 쓰지 않는다. 한국어 설명에서는 기술 토큰만 남은 잔해가
    되고(`2026-09-03-200-ai-3-typescript-200-3`), 읽을 이름은 리포트 제목이 맡는다.
    """
    digest = hashlib.sha256(description.encode()).hexdigest()[:8]
    return f"{today}-{digest}"
