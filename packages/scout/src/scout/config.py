from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """앱 설정. 항목의 정본 목록은 08-설정.md다.

    ★ 범위 제약(`ge`/`le`)이 붙은 필드는 **그 밖의 값이면 시작할 때 터진다.**
    조용히 무시하는 클램프(`max(2, 설정)`)를 쓰지 않는 이유는, "설정 파일에 적은 값과
    실제 동작이 다르다"가 가장 찾기 어려운 버그가 되기 때문이다. `cli.py`가 이미
    `ValidationError`를 잡아 `[FAIL] Settings 로딩 실패`로 찍는다.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    aws_region: str = Field(validation_alias="AWS_DEFAULT_REGION")
    # AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY 는 여기 없다 — boto3가 환경에서 직접 읽는다 (08-설정.md 규칙 2)

    scout_model_id: str = "anthropic.claude-sonnet-5"
    scout_runs_dir: str = "runs"
    scout_max_components: int = Field(default=3, ge=1)
    scout_max_candidates: int = Field(default=3, ge=1)
    scout_interview_max_turns: int = Field(default=5, ge=0)
    scout_llm_concurrency: int = Field(default=4, ge=1)
    scout_mcp_concurrency: int = Field(default=8, ge=1)
    # SCOUT_LOG_LEVEL을 걷어냈다 — 아무도 읽지 않는 죽은 설정이었다. 동작하지 않는
    # 손잡이를 정본 목록에 두면 그게 거짓이 된다. `extra="ignore"`라 남아 있는
    # .env 줄은 그냥 무시된다.

    # ★ Bedrock 호출의 타임아웃·재시도. 이름에 AWS_ 를 쓰지 않는다 (불변식 8) —
    # boto3가 읽는 표준 변수가 아니라 우리가 botocore.Config로 명시 전달하는 값이다.
    #
    # read_timeout 기본이 600초인 이유는 실측이다: botocore 기본 60초에서 design 추출이
    # 죽었다(툴 기록 22회가 담긴 프롬프트에서 Design 구조화 출력을 만드는 데 부족했다).
    # 파이프라인 전체가 거기서 끝났으므로 넉넉하게 잡는다 — 짧아서 죽는 것이
    # 길어서 기다리는 것보다 나쁘다.
    scout_bedrock_read_timeout_seconds: int = Field(default=600, ge=30)
    # 연결은 빠르거나 아예 안 된다. 느리면 리전·자격 문제이므로 오래 기다릴 이유가 없다.
    scout_bedrock_connect_timeout_seconds: int = Field(default=10, ge=1)
    # verify가 4병렬로 돌아 스로틀링에 부딪힌다. 1이면 재시도 없음.
    scout_bedrock_max_attempts: int = Field(default=3, ge=1, le=10)

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

    # MCP stdio 세션의 응답 대기 상한. 서버가 인터넷을 때리는 유일한 출구이고
    # search가 결정 지점을 병렬로 돌리므로, 여기가 hang하면 그 요소가 멈춘 채 남는다.
    scout_mcp_read_timeout_seconds: int = Field(default=60, ge=5)

    # 거부 몇 번에 웹검색을 차단할지. 불변식 14가 요구하는 것은 "거부되면 원본 툴을
    # 부르지 않는다"이고 그건 이 값과 무관하다 — 여기는 운영 정책이다.
    scout_max_search_rejections: int = Field(default=3, ge=1)

    # grounding 위반 시 재판정 횟수. 0이어도 **검출은 남는다** — 절단선 3번이
    # 재판정 루프까지만 잘라도 된다고 한 이유가 그것이다 (3-verify.md).
    scout_max_reground: int = Field(default=1, ge=0, le=3)

    # 후보당 dossier에 넣을 웹 사실 상한 = judge 프롬프트 크기 = 토큰.
    scout_max_web_facts: int = Field(default=6, ge=1)

    # 에이전트 기록을 접을 때 툴 payload 하나를 자르는 길이. 모델을 갈면 따라 움직인다.
    scout_tool_payload_chars: int = Field(default=1200, ge=200)

    # ★ 결정 지점이 성립하는 최소 보기 수 (불변식 18). **하한 2를 여기서 강제한다** —
    # 1이면 "무엇을 고를 것인가"에 답이 하나인 지점이 search로 가고, search가 억지
    # 후보를 만들어 질문에 답하지 않는 후보가 1위로 올라온다 (CHANGELOG v26 실측).
    # 3·4로 올려 조이는 것은 정당한 조절이라 상한은 두지 않는다.
    scout_min_alternatives: int = Field(default=2, ge=2)

    # 1위와 2위의 overall 차이가 이만큼이면 decisive다. overall이 1~5라 상한이 있다.
    scout_decisive_gap: int = Field(default=2, ge=1, le=4)

    # 리포트 표시 길이. 제목 상한은 프롬프트가 요구하는 40자보다 넉넉해야 한다 —
    # 지시 준수가 약한 모델에서도 화면이 버텨야 하고, 40 이하로 내리면 프롬프트를
    # 지킨 제목까지 폴백으로 떨어져 제목이 항상 원문이 된다.
    scout_report_title_chars: int = Field(default=60, ge=40)
    scout_report_summary_chars: int = Field(default=90, ge=30)
    # 보고서 "가장 큰 위험"에 싣는 개수. 0이면 섹션이 사라지므로 하한이 1이다 (불변식 12).
    scout_report_risks: int = Field(default=3, ge=1)
