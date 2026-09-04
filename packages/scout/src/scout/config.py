from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """앱 설정. 항목 설명은 08-설정.md.

    범위 제약을 벗어난 값은 조용히 무시하지 않고 `Settings` 생성에서 실패한다.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 크레덴셜은 여기 없다 — boto3가 환경에서 직접 읽는다 (불변식 9)
    aws_region: str = Field(validation_alias="AWS_DEFAULT_REGION")

    scout_model_id: str = "anthropic.claude-sonnet-5"
    scout_runs_dir: str = "runs"
    scout_max_components: int = Field(default=3, ge=1)
    scout_max_candidates: int = Field(default=3, ge=1)
    scout_interview_max_turns: int = Field(default=5, ge=0)
    scout_llm_concurrency: int = Field(default=4, ge=1)
    scout_mcp_concurrency: int = Field(default=8, ge=1)

    # 이름에 AWS_ 를 쓰지 않는다 — boto3가 읽는 표준 변수가 아니라 botocore.Config로
    # 우리가 넘기는 값이다 (불변식 8)
    scout_bedrock_read_timeout_seconds: int = Field(default=600, ge=30)
    scout_bedrock_connect_timeout_seconds: int = Field(default=10, ge=1)
    scout_bedrock_max_attempts: int = Field(default=3, ge=1, le=10)
    scout_mcp_read_timeout_seconds: int = Field(default=60, ge=5)

    # superstep 수다 — 툴 호출 수는 대략 절반이다
    scout_design_recursion_limit: int = 10
    scout_search_recursion_limit: int = 16

    # design은 실행 전체, search는 결정 지점당
    scout_design_web_searches: int = 3
    scout_search_web_searches: int = 5
    scout_max_search_rejections: int = Field(default=3, ge=1)

    # 개발용. 기본 off — 켜면 어제의 판정이 오늘의 추천으로 나온다
    scout_llm_cache: bool = False
    scout_llm_cache_path: str = "runs/llm-cache.sqlite"

    scout_max_reground: int = Field(default=1, ge=0, le=3)
    scout_max_web_facts: int = Field(default=6, ge=1)
    scout_tool_payload_chars: int = Field(default=1200, ge=200)

    # 하한 2가 불변식 18이다 — 1이면 고를 것이 하나인 지점이 search로 간다
    scout_min_alternatives: int = Field(default=2, ge=2)
    scout_decisive_gap: int = Field(default=2, ge=1, le=4)

    # 하한 40은 프롬프트가 요구하는 제목 길이다 — 그보다 낮으면 폴백만 나온다
    scout_report_title_chars: int = Field(default=60, ge=40)
    scout_report_summary_chars: int = Field(default=90, ge=30)
    scout_report_risks: int = Field(default=3, ge=1)
