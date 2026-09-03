"""npm 레지스트리 — 후보 발견(`npm_search`) + dossier 수집(`npm_package`)
(04-아키텍처.md "MCP 툴 6종").
"""

from urllib.parse import quote

import httpx

from scout_net_mcp import cache
from scout_net_mcp.config import Settings
from scout_net_mcp.egress import check_allowed

_settings = Settings()


async def npm_search(text: str) -> dict:
    """npm 레지스트리 검색 — 질의에 걸린 패키지 목록(이름·설명·버전)."""
    url = f"https://registry.npmjs.org/-/v1/search?text={quote(text)}&size=10"
    cached = cache.get(url, _settings)
    if cached is not None:
        return cached

    await check_allowed(url, _settings)
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=10.0)
        response.raise_for_status()
        data = response.json()

    result = {
        "results": [
            {
                "name": obj["package"]["name"],
                "description": obj["package"].get("description"),
                "version": obj["package"].get("version"),
                "score": obj.get("score", {}).get("final"),
            }
            for obj in data.get("objects", [])
        ]
    }
    cache.set(url, result, _settings)
    return result


async def npm_package(name: str) -> dict:
    """패키지 메타데이터 — 버전·릴리스일·라이선스·deprecated."""
    url = f"https://registry.npmjs.org/{name}"
    cached = cache.get(url, _settings)
    if cached is not None:
        return cached

    await check_allowed(url, _settings)
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=10.0)
        response.raise_for_status()
        data = response.json()

    latest = data.get("dist-tags", {}).get("latest")
    latest_info = data.get("versions", {}).get(latest, {}) if latest else {}
    result = {
        "name": data.get("name", name),
        "latest_version": latest,
        "last_release": data.get("time", {}).get(latest) if latest else None,
        "license": latest_info.get("license"),
        "deprecated": latest_info.get("deprecated"),
        "description": data.get("description"),
        "homepage": data.get("homepage"),
    }
    cache.set(url, result, _settings)
    return result
