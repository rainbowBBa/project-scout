from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """앱(scout)의 Settings와 별개 — import하지 않는다 (워크스페이스 경계, 05-프로젝트관리.md)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    github_token: str | None = None
    scout_egress_allowlist: str = (
        "registry.npmjs.org,api.npmjs.org,pypi.org,api.github.com,api.osv.dev,www.google.com"
    )
    scout_cache_dir: str = ".cache/scout-net"
    scout_cache_ttl_hours: int = 24
    scout_rate_limit_rps: int = 5
    scout_search_provider: str = "ddg"

    # provider 5곳(npm 2 · pypi · github · osv)에 같은 값이 박혀 있던 것을 모았다.
    # 하나만 고치면 나머지가 조용히 남는 형태였다. 10초가 짧다는 건 이미 관측된
    # 사실이다 — 웹검색 승인 프롬프트가 떠 있는 동안 다른 결정 지점의 in-flight
    # 요청이 이 값에서 죽는다 (001/09-출력양식.md · CHANGELOG v29).
    scout_net_http_timeout_seconds: float = Field(default=10.0, gt=0)

    # npm 검색이 받아올 후보 목록 폭. 뒤에서 SCOUT_MAX_CANDIDATES가 자르는데
    # 앞의 이 값만 고정이라 규모 손잡이와 짝이 맞지 않았다.
    scout_net_npm_search_size: int = Field(default=10, ge=1, le=250)
