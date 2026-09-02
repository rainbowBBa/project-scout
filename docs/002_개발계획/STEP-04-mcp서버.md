# STEP 04 · MCP 서버

> 인터넷 출구를 만든다. allowlist·레이트리밋·캐시·감사로그 위에 provider 4종.
> 앱 없이 단독으로 완결되어야 한다.

**선행** STEP 00 (스켈레톤) · **시간** ~3.5h · **설계** [04-아키텍처](../001_기술스택-조사-에이전트-설계/04-아키텍처.md)

## 만들 것
- `scout_net_mcp/config.py` — 서버 전용 `Settings` (앱 것을 import하지 않는다)
- `scout_net_mcp/egress.py` — 도메인 allowlist + 토큰버킷 + 감사로그
- `scout_net_mcp/cache.py` — 디스크 캐시 24h TTL
- `scout_net_mcp/providers/npm.py` — `npm_search` `npm_package`
- `scout_net_mcp/providers/pypi.py` — `pypi_package`
- `scout_net_mcp/providers/github.py` — `github_repo_health`
- `scout_net_mcp/providers/search.py` — `web_search` (DDG, **교체 지점**)
- `tests/test_egress.py`

## 완료 기준
- [ ] 툴 5개를 서버 단독으로 직접 호출해 응답을 확인했다
- [ ] `test_egress.py` 통과 — allowlist 밖 도메인 거부 + 감사로그 기록
- [ ] 캐시 히트 시 HTTP가 발생하지 않는다
- [ ] 후보 10개 dossier 수집이 1분 내
- [ ] 조회 실패가 예외를 던지지 않고 `gaps`용 값으로 격하된다
- [ ] `scout_net_mcp` 가 `scout` 를 import하지 않는다 (grep 0건)
- [ ] MCP 서버 프로세스에 `AWS_*` 환경변수가 **존재하지 않는다** (`env` 필터가 작동)

## 막히면
DDG 패키지 이름이 `duckduckgo-search` → `ddgs`로 개칭된 이력. `uv add` 시점에 확인.
GitHub 토큰 없으면 60req/h — 후보 10개면 1회는 되지만 반복하면 소진된다.
