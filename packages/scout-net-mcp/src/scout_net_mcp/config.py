from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """앱(scout)의 Settings와 별개 — import하지 않는다 (워크스페이스 경계, 05-프로젝트관리.md)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    github_token: str | None = None
    scout_egress_allowlist: str = (
        "registry.npmjs.org,api.npmjs.org,pypi.org,api.github.com,"
        "api.osv.dev,html.duckduckgo.com"
    )
    scout_cache_dir: str = ".cache/scout-net"
    scout_cache_ttl_hours: int = 24
    scout_rate_limit_rps: int = 5
    scout_search_provider: str = "ddg"
