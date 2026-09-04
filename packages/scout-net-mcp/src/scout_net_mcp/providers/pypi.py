"""PyPI — dossier 수집 (04-아키텍처.md "MCP 툴 6종")."""

import httpx

from scout_net_mcp import cache
from scout_net_mcp.config import Settings
from scout_net_mcp.egress import check_allowed

_settings = Settings()


async def pypi_package(name: str) -> dict:
    """패키지 메타데이터 — 버전·릴리스일·라이선스·yanked 여부."""
    url = f"https://pypi.org/pypi/{name}/json"
    cached = cache.get(url, _settings)
    if cached is not None:
        return cached

    await check_allowed(url, _settings)
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=_settings.scout_net_http_timeout_seconds)
        response.raise_for_status()
        data = response.json()

    info = data.get("info", {})
    latest_version = info.get("version")
    latest_files = data.get("releases", {}).get(latest_version, []) if latest_version else []
    upload_time = latest_files[0].get("upload_time") if latest_files else None
    yanked = any(f.get("yanked") for f in latest_files)

    result = {
        "name": info.get("name", name),
        "latest_version": latest_version,
        "last_release": upload_time,
        "license": info.get("license"),
        "yanked": yanked,
        "summary": info.get("summary"),
        "homepage": info.get("home_page") or info.get("project_url"),
    }
    cache.set(url, result, _settings)
    return result
