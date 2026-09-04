"""OSV — 알려진 취약점 조회 (04-아키텍처.md "MCP 툴 7종").

★ **버전을 반드시 함께 보낸다.** 버전 없이 조회하면 OSV는 그 패키지에 **한 번이라도**
영향을 준 취약점을 전부 돌려준다. 그러면 오래 유지된 성숙한 패키지가 "취약점 30건"으로
나와 `rubric.risk`에서 감점되고, **성숙도가 위험으로 뒤집힌다.** 판단에 쓸 사실은
"지금 설치될 버전이 영향을 받는가"다. 그래서 `version`이 필수 인자다 —
`search`의 top-up이 레지스트리에서 읽은 `latest_version`을 그대로 넘긴다.
"""

import httpx

from scout_net_mcp import cache
from scout_net_mcp.config import Settings
from scout_net_mcp.egress import check_allowed

_settings = Settings()

_URL = "https://api.osv.dev/v1/query"

# GHSA가 쓰는 등급. 높은 것이 앞 — max_severity는 이 순서로 고른다.
_SEVERITY_ORDER = ("CRITICAL", "HIGH", "MODERATE", "MEDIUM", "LOW")
_MAX_IDS = 5

# OSV의 ecosystem 표기는 대소문자를 가린다 — "PyPI"를 "pypi"로 보내면 0건이 온다.
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
    """등급 한 단어를 뽑는다. **CVSS 벡터는 파싱하지 않는다** — 없으면 등급 없음이다.

    `database_specific.severity`는 GHSA 유래 항목에 들어 있어 npm·PyPI는 대부분 채워진다.
    벡터(`CVSS:3.1/AV:N/…`)에서 기본점수를 계산하는 건 이 프로토타입의 범위 밖이고,
    모르는 것을 추측해 채우면 `risk`가 근거 없이 흔들린다 — 없는 건 없다고 둔다.
    """
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
    """알려진 취약점 — 지정한 **버전이 영향받는** 것만 센다.

    `ecosystem`은 `npm` 또는 `PyPI`(대소문자 무관). `version`은 레지스트리에서 읽은
    설치 대상 버전을 넣는다 — 버전 없이 물으면 이미 고쳐진 과거 취약점까지 세어
    성숙한 패키지가 위험해 보인다.
    """
    resolved = _ECOSYSTEMS.get(ecosystem.strip().lower(), ecosystem.strip())
    # 캐시 키가 URL이면 POST 본문이 달라도 같은 키가 된다 — 조회 대상을 키에 넣는다.
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
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()

    # 취약점이 없으면 OSV는 `{"vulns": []}`가 아니라 빈 객체를 돌려준다.
    vulns = [v for v in (data.get("vulns") or []) if isinstance(v, dict)]
    ids = [v["id"] for v in vulns if v.get("id")]

    result = {
        "name": name,
        "ecosystem": resolved,
        "version": version,
        "vulns": len(vulns),
        # 0건이면 등급도 ID도 없다 — 빈 값을 만들어 넣지 않는다 (search가 사실에서 뺀다).
        "max_severity": _max_severity(vulns),
        "ids": ", ".join(ids[:_MAX_IDS]),
        "url": f"https://osv.dev/list?q={name}&ecosystem={resolved}",
    }
    cache.set(key, result, _settings)
    return result
