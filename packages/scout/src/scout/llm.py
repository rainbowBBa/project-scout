from langchain_aws import ChatBedrockConverse

from scout.config import Settings


def make_llm(settings: Settings) -> ChatBedrockConverse:
    return ChatBedrockConverse(
        model=settings.scout_model_id,
        region_name=settings.aws_region,
        credentials_profile_name=settings.aws_profile,
    )
