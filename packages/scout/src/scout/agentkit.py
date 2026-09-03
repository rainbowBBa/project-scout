"""ReAct 에이전트 기록을 코드가 읽는 장치 — `design`과 `search`가 공유한다.

두 단계 다 `create_agent`로 툴을 부르게 하고, **결과는 LLM 문장이 아니라
`ToolMessage` 원본에서 코드가 뽑는다.** `search`는 그 값으로 dossier를 만들고
(불변식 13), `design`은 설계 어휘만 얻고 **`facts`에는 넣지 않는다**(불변식 15).

단계별 모듈이 아니라 여기 있는 이유는 stage → stage import를 만들지 않기 위해서다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from langchain_core.messages import BaseMessage

_TOOL_PAYLOAD_CHARS = 1200


async def run_agent_loop(agent, task: str, limit: int) -> tuple[list, bool]:
    """툴 루프를 돌리고 (메시지, 한도에 걸렸는지)를 돌려준다.

    `ainvoke`가 아니라 `astream`을 쓰는 이유는 **한도 초과가 예외이기 때문**이다 —
    `GraphRecursionError`는 상태를 담아주지 않아서 `ainvoke`로 받으면 그때까지 모은
    툴 기록이 함께 날아간다. 한도를 낮춘 만큼 걸릴 일이 실제로 생기고, 그때 부분
    기록만으로도 결과를 뽑는 게 아무것도 없이 죽는 것보다 낫다 (불변식 11).

    `limit`은 **툴 호출 수가 아니라 superstep 수**다. ReAct는 한 바퀴가 model + tools
    두 스텝이라 10이면 툴 호출 4~5회쯤이다. `create_agent`는 그래프에 9999를 바인딩해
    두므로 호출할 때마다 반드시 넘긴다.
    """
    messages: list = []
    try:
        async for state in agent.astream(
            {"messages": [HumanMessage(task)]},
            config={"recursion_limit": limit},
            stream_mode="values",
        ):
            messages = state["messages"]
    except GraphRecursionError:
        return messages, True
    return messages, False


@dataclass
class ToolCall:
    name: str
    args: dict
    payload: dict | None
    raw: str


def message_text(message: Any) -> str:
    """`.text`는 langchain-core 1.x에서 메서드 → 프로퍼티로 바뀌었다.

    호환 기간이라 프로퍼티가 **호출도 되는** 문자열을 돌려준다 — `callable()`을 먼저
    보면 구형 경로로 빠져 deprecation 경고가 뜬다. 문자열 판정을 앞에 둔다.
    """
    text = getattr(message, "text", None)
    if isinstance(text, str):
        return text
    if callable(text):
        return str(text())
    return str(getattr(message, "content", ""))


def parse_payload(content: Any) -> dict | None:
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        # MCP content 블록 리스트 — text 조각만 이어붙인다
        text = "".join(
            b.get("text", "") for b in content if isinstance(b, dict) and "text" in b
        )
        return parse_payload(text) if text else None
    if not isinstance(content, str):
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def collect_tool_calls(messages: Sequence[BaseMessage]) -> list[ToolCall]:
    """`ToolMessage`를 `tool_call_id`로 원래 tool_call과 이어 붙인다."""
    args_by_id: dict[str, tuple[str, dict]] = {}
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            args_by_id[call["id"]] = (call["name"], call.get("args") or {})

    calls = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        name, args = args_by_id.get(message.tool_call_id, (message.name or "", {}))
        raw = message_text(message)
        calls.append(
            ToolCall(
                name=name, args=args, payload=parse_payload(message.content), raw=raw
            )
        )
    return calls


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}… (생략)"


def build_transcript(calls: Sequence[ToolCall], messages: Sequence[BaseMessage]) -> str:
    """에이전트 히스토리를 평문으로 접는다.

    원본 메시지를 그대로 다음 프롬프트에 넣으면 tool_use/tool_result 쌍이 새 toolConfig와
    맞지 않아 Bedrock이 거부할 수 있다. 평문이면 그 문제가 없고 토큰도 준다.
    """
    lines = []
    for call in calls:
        lines.append(f"[{call.name}] {json.dumps(call.args, ensure_ascii=False)}")
        lines.append(_truncate(call.raw, _TOOL_PAYLOAD_CHARS))
    final = [
        m for m in messages if isinstance(m, AIMessage) and message_text(m).strip()
    ]
    if final:
        lines.append(f"[에이전트 요약] {message_text(final[-1]).strip()}")
    return "\n".join(lines) or "(툴 호출 없음)"
