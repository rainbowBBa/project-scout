# STEP 05 · search

> 요소당 후보 2~3개를 찾고 kind별로 dossier를 모은다.
> LLM 질의생성 → 코드가 MCP 실행 → LLM 랭킹. 3턴이고 에이전트가 아니다.

**선행** STEP 03, STEP 04 · **시간** ~1.5h · **설계** [stages/2-search](../001_기술스택-조사-에이전트-설계/stages/2-search.md)

## 만들 것
- `scout/mcp_client.py` — `MultiServerMCPClient` 래퍼 + **자식 프로세스 `env` 필터**
- `scout/stages/search.py` — 3턴 + kind 라우팅
- `scout/graph.py` — `Send` fan-out (요소별) + `Semaphore`(LLM 4, MCP 8)

## 완료 기준
- [ ] MCP 툴이 LangChain `BaseTool`로 로드된다
- [ ] `candidates` 8~10행, `facts` 30~80행이 생긴다
- [ ] `Fact.id`가 `<출처>.<항목>` 규칙을 따른다 (`npm.last_release` 등)
- [ ] `method` 후보의 `gaps`에 "레지스트리 없음"이 기록된다
- [ ] 요소 하나가 실패해도 나머지가 계속 돈다
- [ ] `--max-candidates 3` 이 요소당 후보 수를 제한한다

## 막히면
DDG 스니펫 품질이 나빠 후보가 엉뚱하면 `npm_search`를 주력으로 두고 `web_search` 가중치를 낮춘다.
ReAct 에이전트로 바꾸려는 충동을 참는다 — Sonnet + DDG 조합에서 헤맨다.
