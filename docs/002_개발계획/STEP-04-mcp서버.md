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
- `scout_net_mcp/providers/search.py` — `web_search` (`ddgs` + Google backend, **교체 지점**)
- `tests/test_egress.py`

## 완료 기준
- [x] 툴 5개를 서버 단독으로 직접 호출해 응답을 확인했다 (직접 호출 + 실제 MCP
  stdio 프로토콜 양쪽으로 확인)
- [x] `test_egress.py` 통과 — allowlist 밖 도메인 거부 + 감사로그 기록
- [x] 캐시 히트 시 HTTP가 발생하지 않는다 (두 번째 호출 15ms — 디스크 읽기뿐)
- [x] 후보 10개 dossier 수집이 1분 내 (근사 검증: 서로 다른 패키지 10개 ×
  npm_package+github_repo_health 병렬 호출 — 2.1초)
- [x] 조회 실패가 예외를 던지지 않고 `gaps`용 값으로 격하된다 — 정확히는:
  scout_net_mcp는 `gaps` 개념을 모른다(scout를 import 안 함). 여기서 보장하는
  건 실패가 **깨끗한 예외로 격하**되어 서버 프로세스가 죽지 않는다는 것까지다
  (404로 확인, 이후 호출도 정상 동작). `gaps` 테이블 기록은 앱 쪽(STEP-05
  `search.py`)이 이 예외를 잡아서 한다
- [x] `scout_net_mcp` 가 `scout` 를 import하지 않는다 (grep 0건)
- [x] MCP 서버 프로세스에 `AWS_*` 환경변수가 **존재하지 않는다** (`env` 필터가 작동 —
  `scout/mcp_client.py`의 `_server_env()`로 확인)

## 막히면
DDG 패키지 이름이 `duckduckgo-search` → `ddgs`로 개칭된 이력. `uv add` 시점에 확인.
GitHub 토큰 없으면 60req/h — 후보 10개면 1회는 되지만 반복하면 소진된다.

**구현 중 발견한 것**: `ddgs`(옛 duckduckgo-search)는 `backend` 인자를 안 주면
`"auto"`로 bing·google·mojeek·wikipedia·grokipedia까지 섞어 쓴다 — 재현성이
없어서 못 쓴다. 처음엔 패키지 이름을 따라 `backend="duckduckgo"`로 고정했는데,
"패키지 선택과 검색엔진 선택은 별개다, 목적에 더 잘 맞는 걸 써라"는 지적을
받고 두 시나리오로 실제 결과 품질을 비교했다: `duckduckgo`는 한 시나리오에서
아예 결과 0건이 나왔고, `google`은 두 시나리오 다 Hacker News·Reddit 토론
스레드를 포함해 "이 방법이 실제로 괜찮은가"를 판단할 근거로 가장 값어치
있었다. 최종적으로 `backend="google"`로 바꿨다 — 자세한 비교는
[001/CHANGELOG v15](../001_기술스택-조사-에이전트-설계/CHANGELOG.md).

실제로 맞는 호스트는 검색엔진에 따라 다르다(`html.duckduckgo.com`이 아니라
`www.google.com`) — `SCOUT_EGRESS_ALLOWLIST` 기본값도 그에 맞춰 고쳤다
(`.env.example`, `scout_net_mcp/config.py`). 다만 `ddgs`는 자체 HTTP
클라이언트(`primp`)로 요청해서 `check_allowed()`가 그 요청을 실제로
가로막지는 못한다 — allowlist·감사로그 관점에서 상징적인 체크임을
`providers/search.py`에 주석으로 남겼다.
