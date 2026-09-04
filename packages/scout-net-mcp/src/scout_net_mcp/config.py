from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """앱(scout)의 Settings와 별개 — import하지 않는다 (불변식 1)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    github_token: str | None = None
    scout_egress_allowlist: str = (
        "registry.npmjs.org,api.npmjs.org,pypi.org,api.github.com,api.osv.dev,www.google.com"
    )
    scout_cache_dir: str = ".cache/scout-net"
    scout_cache_ttl_hours: int = 24
    scout_rate_limit_rps: int = 5
    scout_search_provider: str = "ddg"

    # provider 전체가 공유하는 인터넷 대기 상한. 재시도는 없다 (불변식 11)
    scout_net_http_timeout_seconds: float = Field(default=10.0, gt=0)
    scout_net_npm_search_size: int = Field(default=10, ge=1, le=250)
