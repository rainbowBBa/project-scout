"""OSV — 알려진 취약점 조회 (04-아키텍처.md).

`version`이 필수 인자인 이유: 버전 없이 조회하면 그 패키지에 한 번이라도 영향을 준
취약점이 전부 와서, 오래 유지된 패키지가 `rubric.risk`에서 감점된다.
"""

import httpx

from scout_net_mcp import cache
from scout_net_mcp.config import Settings
from scout_net_mcp.egress import check_allowed

_settings = Settings()

_URL = "https://api.osv.dev/v1/query"

# 높은 것이 앞. 유효성 검사에도 쓰므로 GHSA 어휘와 정확히 일치해야 한다
_SEVERITY_ORDER = ("CRITICAL", "HIGH", "MODERATE", "MEDIUM", "LOW")
_MAX_IDS = 5

# 대소문자를 가린다 — "PyPI"를 "pypi"로 보내면 0건이 온다
_ECOSYSTEMS = {
    "npm": "npm",
    "pypi": "PyPI",
    "go": "Go",
    "crates.io": "crates.io",
    "cargo": "crates.io",
    "maven": "Maven",
    "nuget": "NuGet",
    "packagist": "Packagist",
    "rubygems": "RubyGems",
}


def _severity_of(vuln: dict) -> str | None:
    """등급 한 단어를 뽑는다. CVSS 벡터는 파싱하지 않는다 — 없으면 등급 없음이다."""
    raw = (vuln.get("database_specific") or {}).get("severity")
    if not isinstance(raw, str):
        return None
    upper = raw.strip().upper()
    return upper if upper in _SEVERITY_ORDER else None


def _max_severity(vulns: list[dict]) -> str | None:
    found = {s for s in (_severity_of(v) for v in vulns) if s}
    for level in _SEVERITY_ORDER:
        if level in found:
            return level
    return None


async def osv_query(name: str, ecosystem: str, version: str) -> dict:
    """알려진 취약점 — 지정한 버전이 영향받는 것만 센다.

    `ecosystem`은 `npm` 또는 `PyPI`(대소문자 무관). `version`은 레지스트리에서 읽은
    설치 대상 버전을 넣는다.
    """
    resolved = _ECOSYSTEMS.get(ecosystem.strip().lower(), ecosystem.strip())
    # POST라 URL이 같다 — 조회 대상을 키에 넣는다
    key = f"osv:{resolved}:{name}@{version}"
    cached = cache.get(key, _settings)
    if cached is not None:
        return cached

    await check_allowed(_URL, _settings)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            _URL,
            json={
                "package": {"name": name, "ecosystem": resolved},
                "version": version,
            },
            timeout=_settings.scout_net_http_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()

    # 취약점이 없으면 `{"vulns": []}`가 아니라 빈 객체가 온다
    vulns = [v for v in (data.get("vulns") or []) if isinstance(v, dict)]
    ids = [v["id"] for v in vulns if v.get("id")]

    result = {
        "name": name,
        "ecosystem": resolved,
        "version": version,
        "vulns": len(vulns),
        # 0건이면 등급도 ID도 없다 — 빈 값은 사실이 되지 않는다
        "max_severity": _max_severity(vulns),
        "ids": ", ".join(ids[:_MAX_IDS]),
        "url": f"https://osv.dev/list?q={name}&ecosystem={resolved}",
    }
    cache.set(key, result, _settings)
    return result
