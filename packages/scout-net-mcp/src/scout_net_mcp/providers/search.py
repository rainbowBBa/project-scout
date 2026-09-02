"""웹 검색 — `method` 후보(아키텍처 패턴 등)의 유일한 근거 (04-아키텍처.md).
DuckDuckGo, 프로토타입용 **교체 지점**. 사내 검색 API가 생기면 이 함수만
갈아끼운다 — `SCOUT_SEARCH_PROVIDER`.

패키지 이름이 `duckduckgo-search` → `ddgs`로 개칭된 이력이 있다 (STEP-04 "막히면").
"""

import asyncio

from ddgs import DDGS

from scout_net_mcp import cache
from scout_net_mcp.config import Settings
from scout_net_mcp.egress import check_allowed

_settings = Settings()


def _search_sync(query: str, n: int) -> list[dict]:
    # backend를 명시하지 않으면 ddgs가 "auto"로 bing·google·mojeek·wikipedia까지
    # 멋대로 섞어 쓴다 — 설계 문서가 정한 DuckDuckGo 하나만 쓰도록 고정한다.
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=n, backend="duckduckgo"))


async def web_search(query: str, n: int = 5) -> dict:
    """DDG 검색 결과 상위 n개 — title/url/snippet."""
    cache_key = f"ddg:{query}:{n}"
    cached = cache.get(cache_key, _settings)
    if cached is not None:
        return cached

    # ddgs는 자체 HTTP 클라이언트(primp)로 요청한다 — 이 httpx 기반 egress
    # 게이트를 실제로 통과하지 않는다. allowlist에 html.duckduckgo.com을
    # 두고 backend="duckduckgo"로 고정하는 것까지가 이 프로토타입에서 강제할
    # 수 있는 범위다 — 감사로그·레이트리밋 관점에서는 상징적인 체크임을
    # 명시해둔다.
    await check_allowed("https://html.duckduckgo.com/html/", _settings)
    # ddgs는 동기 라이브러리다 — 이벤트 루프를 막지 않도록 스레드에서 돌린다.
    raw_results = await asyncio.to_thread(_search_sync, query, n)

    result = {
        "results": [
            {
                "title": r.get("title"),
                "url": r.get("href"),
                "snippet": r.get("body"),
            }
            for r in raw_results
        ]
    }
    cache.set(cache_key, result, _settings)
    return result
