from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    aws_region: str = Field(validation_alias="AWS_DEFAULT_REGION")
    # AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY 는 여기 없다 — boto3가 환경에서 직접 읽는다 (08-설정.md 규칙 2)

    scout_model_id: str = "anthropic.claude-sonnet-5"
    scout_runs_dir: str = "runs"
    scout_max_components: int = 3
    scout_max_candidates: int = 3
    scout_llm_concurrency: int = 4
    scout_mcp_concurrency: int = 8
    scout_log_level: str = "info"
