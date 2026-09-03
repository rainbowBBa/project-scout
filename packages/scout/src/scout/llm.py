import contextlib
from typing import Any

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from pydantic import BaseModel, ValidationError

from scout.config import Settings


def make_llm(settings: Settings) -> ChatBedrockConverse:
    return ChatBedrockConverse(
        model=settings.scout_model_id,
        region_name=settings.aws_region,
    )


def _salvage(result: dict, schema: type[BaseModel] | None) -> Any:
    """파싱 실패를 같은 응답 안에서 구제한다 — 재시도(=LLM 1회) 전에 먼저 해본다.

    `with_structured_output`의 파서는 `first_tool_only=True`라 **첫 `tool_call`만**
    본다. 모델이 `tool_use` 블록을 두 개 낼 때(스키마가 크면 실측으로 일어난다) 첫
    블록이 불완전하면 **같은 응답에 완전한 블록이 있어도 전체가 실패한다.**
    남은 블록을 훑어 유효한 것을 쓴다.
    """
    if result["parsed"] is not None:
        return result["parsed"]
    if schema is None:
        return None

    calls = getattr(result["raw"], "tool_calls", None) or []
    args = [call.get("args") or {} for call in calls]

    # 병합을 먼저 시도한다 — 모델이 **한 객체를 여러 블록으로 쪼개** 보내는 것이
    # 실측된다 (`Design`이 architecture / components 로 갈렸다). 개별 블록을 먼저
    # 채택하면 필드가 전부 optional인 스키마에서 나머지 블록의 값을 조용히 버린다.
    if len(args) > 1:
        merged: dict = {}
        for one in args:
            merged.update(one)
        with contextlib.suppress(ValidationError):
            return schema.model_validate(merged)

    for one in args:
        with contextlib.suppress(ValidationError):
            return schema.model_validate(one)
    return None


def invoke_structured(
    prompt: ChatPromptTemplate,
    structured_llm: Runnable,
    prompt_input: dict,
    retry_hint: str,
    *,
    schema: type[BaseModel] | None = None,
) -> tuple[Any, Any]:
    """parsed가 None이면 retry_hint를 붙여 1회 재시도한다. (parsed, raw) 반환.

    `schema`를 주면 재시도 전에 같은 응답의 다른 `tool_call`을 먼저 훑는다
    (`_salvage`). 호출을 아끼는 것이면서, 응답에 답이 있는데 파서가 못 본 경우를
    막는다.

    실패 시 `raw`에 `parsing_error`를 붙여 돌려준다 — 그게 없으면 호출부의 예외
    메시지가 원본 payload만 뱉어서 원인 진단이 로그 고고학이 된다.
    """
    result = (prompt | structured_llm).invoke(prompt_input)
    parsed = _salvage(result, schema)
    if parsed is None:
        retry_messages = [
            *prompt.invoke(prompt_input).to_messages(),
            HumanMessage(retry_hint),
        ]
        result = structured_llm.invoke(retry_messages)
        parsed = _salvage(result, schema)
    if parsed is None:
        return None, f"{result.get('parsing_error')} | raw={result['raw']}"
    return parsed, result["raw"]
