"""StateGraph 골격. 노드는 단계마다 하나씩 늘어난다 — 지금은 evaluate까지다.

thread_id = slug 로 SqliteSaver 체크포인터를 물려서, 같은 slug로 다시 실행하면
LangGraph가 끝난 노드를 건너뛰고 이어서 돈다 (02-파이프라인.md "재개").
"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

from scout.stages import analyze as analyze_stage
from scout.stages import evaluate as evaluate_stage
from scout.stages import interview as interview_stage
from scout.stages import search as search_stage
from scout.stages import verify as verify_stage
from scout.state import ScoutState

if TYPE_CHECKING:
    from langchain_aws import ChatBedrockConverse
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from scout.stages.search import Approve


def build_graph(
    llm: ChatBedrockConverse,
    checkpointer: BaseCheckpointSaver,
    *,
    approve: Approve = search_stage.default_approve,
):
    graph = StateGraph(ScoutState)
    graph.add_node(
        "interview", lambda state: interview_stage.interview_node(state, llm=llm)
    )
    graph.add_node("analyze", lambda state: analyze_stage.analyze_node(state, llm=llm))
    graph.add_node(
        "search",
        lambda state: search_stage.search_node(state, llm=llm, approve=approve),
    )
    graph.add_node("verify", lambda state: verify_stage.verify_node(state, llm=llm))
    graph.add_node(
        "evaluate", lambda state: evaluate_stage.evaluate_node(state, llm=llm)
    )
    graph.add_edge(START, "interview")
    graph.add_edge("interview", "analyze")
    graph.add_edge("analyze", "search")
    graph.add_edge("search", "verify")
    graph.add_edge("verify", "evaluate")
    graph.add_edge("evaluate", END)
    return graph.compile(checkpointer=checkpointer)


_SLUG_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def make_slug(description: str, *, today: str) -> str:
    """설명에서 slug를 만든다 — ASCII 단어만 뽑고, 하나도 없으면 설명 해시로 대체한다.

    같은 날 같은 설명으로 다시 실행하면 같은 slug가 나와 체크포인터가 이어서 돈다
    (stages/0-interview.md "같은 slug로 다시 실행하면 이어서 돈다").
    """
    words = _SLUG_WORD_RE.findall(description.lower())
    if words:
        tail = "-".join(words)[:40].rstrip("-")
    else:
        # hash()는 프로세스마다 랜덤이라 재실행 시 같은 slug가 안 나온다 — sha256을 쓴다.
        tail = f"run-{hashlib.sha256(description.encode()).hexdigest()[:8]}"
    return f"{today}-{tail}"
