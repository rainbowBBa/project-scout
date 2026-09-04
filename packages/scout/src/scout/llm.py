import contextlib
from typing import Any

from botocore.config import Config
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from pydantic import BaseModel, ValidationError

from scout.config import Settings


def bedrock_config(settings: Settings) -> Config:
    """Bedrock 호출의 타임아웃·재시도.

    `ChatBedrockConverse`의 `timeout=`·`max_retries=`를 쓰지 않는 이유: `timeout=`은
    connect와 read를 같은 값으로 묶고, `max_retries=`는 retry mode를 못 정한다.

    mode는 `standard`여야 한다 — 기본 `legacy`는 `ThrottlingException` 처리가 좁다.
    `adaptive`는 클라이언트 측 레이트리미팅이 붙어 `Semaphore`와 이중이 된다.
    """
    return Config(
        connect_timeout=settings.scout_bedrock_connect_timeout_seconds,
        read_timeout=settings.scout_bedrock_read_timeout_seconds,
        retries={
            "max_attempts": settings.scout_bedrock_max_attempts,
            "mode": "standard",
        },
    )


def make_llm(settings: Settings) -> ChatBedrockConverse:
    return ChatBedrockConverse(
        model=settings.scout_model_id,
        region_name=settings.aws_region,
        config=bedrock_config(settings),
    )


def _salvage(result: dict, schema: type[BaseModel] | None) -> Any:
    """파싱 실패를 같은 응답 안에서 구제한다 — 재시도 전에 먼저 해본다.

    `with_structured_output`의 파서는 `first_tool_only=True`라 첫 `tool_call`만 본다.
    모델이 `tool_use` 블록을 여러 개 내면 같은 응답에 완전한 블록이 있어도 전체가
    실패하므로, 남은 블록을 훑는다.
    """
    if result["parsed"] is not None:
        return result["parsed"]
    if schema is None:
        return None

    calls = getattr(result["raw"], "tool_calls", None) or []
    args = [call.get("args") or {} for call in calls]

    # 병합을 먼저 한다 — 모델이 한 객체를 여러 블록으로 쪼개기도 한다. 개별 블록을
    # 먼저 채택하면 필드가 전부 optional인 스키마에서 나머지 값을 조용히 버린다.
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

    실패 시 `raw`에 `parsing_error`를 붙인다 — 없으면 호출부 예외가 원본 payload만
    뱉어 원인을 알 수 없다.
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
