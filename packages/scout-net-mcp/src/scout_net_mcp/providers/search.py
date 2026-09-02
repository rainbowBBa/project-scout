"""웹 검색 — `method` 후보(아키텍처 패턴 등)의 유일한 근거 (04-아키텍처.md).
`ddgs` 라이브러리(옛 `duckduckgo-search`, STEP-04 "막히면")로 검색하되,
엔진은 `backend="google"`로 고정한다 — 이유는 아래 참고.
프로토타입용 **교체 지점**. 사내 검색 API가 생기면 이 함수만 갈아끼운다 —
`SCOUT_SEARCH_PROVIDER`.

### 왜 google이고 "duckduckgo" backend가 아닌가

`ddgs`는 duckduckgo·bing·google·mojeek 등 여러 검색엔진을 backend로 고를 수
있는 라이브러리다(패키지 이름과 실제 검색엔진은 별개). backend를 안 정하면
"auto"로 여러 엔진을 멋대로 섞어 쓰는데, 이건 재현성이 없어서 못 쓴다.
STEP-04 구현 중 "method 후보의 유일한 근거"라는 목적에 맞춰 실제 결과 품질을
비교했다:

- `duckduckgo` — 두 시나리오 중 하나에서 아예 결과 0건("No results found").
  나머지 하나도 LinkedIn pulse·일반 블로그 위주로 신호가 약했다
- `bing` — 두 시나리오 다 결과는 나왔고, 품질 있는 전문 블로그를 포함했다
- `google` — 두 시나리오 다 결과가 나왔고, Hacker News·Reddit 토론 스레드를
  일관되게 포함했다 — "이 방법이 실제로 괜찮은가"를 판단할 근거로 가장 값어치
  있는 소스다

`google`로 고정한다. 사설 스크래핑이라 차단 위험이 이론상 더 크지만, 이
프로토타입 규모(실행당 질의 몇 건)에서는 품질·커버리지 이득이 더 크다고 판단
했다 — `duckduckgo-search`라는 옛 패키지 이름이 주는 인상과 달리, 이 선택은
패키지가 아니라 실제로 나온 결과를 보고 정했다.
"""

import asyncio

from ddgs import DDGS

from scout_net_mcp import cache
from scout_net_mcp.config import Settings
from scout_net_mcp.egress import check_allowed

_settings = Settings()

_BACKEND = "google"


def _search_sync(query: str, n: int) -> list[dict]:
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=n, backend=_BACKEND))


async def web_search(query: str, n: int = 5) -> dict:
    """웹 검색 결과 상위 n개 — title/url/snippet."""
    cache_key = f"{_BACKEND}:{query}:{n}"
    cached = cache.get(cache_key, _settings)
    if cached is not None:
        return cached

    # ddgs는 자체 HTTP 클라이언트(primp)로 요청한다 — 이 httpx 기반 egress
    # 게이트를 실제로 통과하지 않는다. allowlist에 실제 요청 호스트를 두고
    # backend를 고정하는 것까지가 이 프로토타입에서 강제할 수 있는 범위다 —
    # 감사로그·레이트리밋 관점에서는 상징적인 체크임을 명시해둔다.
    await check_allowed("https://www.google.com/wml/search", _settings)
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
