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
    scout_interview_max_turns: int = 5
    scout_llm_concurrency: int = 4
    scout_mcp_concurrency: int = 8
    scout_log_level: str = "info"

    # 툴 루프 상한 — LangGraph의 **superstep 수**지 툴 호출 수가 아니다.
    # ReAct는 한 바퀴가 model + tools 두 스텝이라 대략 절반이 툴 호출이다.
    # 코드 상수가 아니라 여기 있는 이유: 규모 조절은 코드를 고치지 않는다.
    scout_design_recursion_limit: int = 10
    scout_search_recursion_limit: int = 16

    # 승인되는 웹검색 상한. design은 실행 전체, search는 결정 지점당이다 —
    # 설계는 요소별로 펼치지 않고 한 번 돌기 때문이다.
    scout_design_web_searches: int = 3
    scout_search_web_searches: int = 5

    # ★ 개발용 LLM 응답 캐시. 기본 off — 이 도구의 값어치는 사실의 신선도이고,
    # 캐시가 켜진 실전 실행은 어제의 판정을 오늘의 추천으로 내놓는다 (07-검증.md).
    scout_llm_cache: bool = False
    scout_llm_cache_path: str = "runs/llm-cache.sqlite"
