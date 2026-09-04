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

    ★ **botocore 기본 read_timeout 60초에서 `design` 추출이 죽었다** — 툴 기록 22회가
    담긴 프롬프트로 `Design` 구조화 출력을 만드는 데 부족했고, 파이프라인 전체가
    거기서 끝났다. 짧아서 죽는 것이 길어서 기다리는 것보다 나쁘다.

    `ChatBedrockConverse`의 `timeout=`을 쓰지 않는 이유는 그 인자가 connect와 read를
    **같은 값으로 묶기** 때문이다. 연결은 빠르거나 아예 안 되므로(느리면 리전·자격
    문제다) 따로 잡아야 하고, `max_retries=`도 `max_attempts`만 정해 mode를 못 바꾼다.

    retry mode를 `standard`로 준다 — 기본 `legacy`는 `ThrottlingException` 처리가 좁고
    `verify`가 후보를 병렬로 돌려 스로틀링에 부딪힌다. `adaptive`는 클라이언트 측
    레이트리미팅이 붙어 우리 `Semaphore`와 이중이 되므로 쓰지 않는다.
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
