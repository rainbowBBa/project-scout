from typing import Any

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from scout.config import Settings


def make_llm(settings: Settings) -> ChatBedrockConverse:
    return ChatBedrockConverse(
        model=settings.scout_model_id,
        region_name=settings.aws_region,
    )


def invoke_structured(
    prompt: ChatPromptTemplate,
    structured_llm: Runnable,
    prompt_input: dict,
    retry_hint: str,
) -> tuple[Any, Any]:
    """parsed가 None이면 retry_hint를 붙여 1회 재시도한다. (parsed, raw) 반환."""
    result = (prompt | structured_llm).invoke(prompt_input)
    parsed = result["parsed"]
    if parsed is None:
        retry_messages = [
            *prompt.invoke(prompt_input).to_messages(),
            HumanMessage(retry_hint),
        ]
        result = structured_llm.invoke(retry_messages)
        parsed = result["parsed"]
    return parsed, result["raw"]
