# STEP 05 · search

> 요소당 ReAct 에이전트 하나가 툴을 골라 후보를 찾고 dossier를 모은다.
> 웹검색은 사람 승인을 거친다. 사실 값은 에이전트가 아니라 코드가 툴 원본에서 뽑는다.

**선행** STEP 03, STEP 04 · **시간** ~2h · **설계** [stages/2-search](../001_기술스택-조사-에이전트-설계/stages/2-search.md)

## 만들 것
- `scout/stages/search.py` — 승인 게이트 + ReAct 루프 + 사실 추출 + kind별 보충
- `scout/schemas.py` — `CandidateDraft` · `CandidateList` (dossier 없는 후보 초안)
- `scout/prompts.py` — `SEARCH_AGENT_SYSTEM_PROMPT` · `SEARCH_EXTRACT_PROMPT`
- `scout/graph.py` — `analyze → search → END`
- `scout/cli.py` — `IMPLEMENTED_STAGES`에 `search`, 단계 요약, `--auto-approve-search`
- `tests/test_search_approval.py` — 승인 게이트 배선

## 완료 기준
- [x] MCP 툴이 LangChain `BaseTool`로 로드되고 에이전트가 **여러 번** 호출한다
- [x] `Fact.id`가 `<출처>.<항목>` 규칙을 따른다 (`npm.last_release` 등)
- [x] `Fact.value`가 `ToolMessage` 원본에서 나온다 — 에이전트 문장이 아니다
- [x] 웹검색 전에 `"<질의>"를 검색하려고 합니다 확인 바랍니다`가 뜬다
- [x] **거부하면 원본 툴이 호출되지 않는다** (egress 0) — `test_search_approval`
- [x] 거부 사유가 에이전트에 돌아가 **질의가 바뀐다** (실측: 고유명사 지적 → 일반 용어로 전환)
- [x] 요소당 웹검색이 5회를 넘지 않는다 (예산 없을 때 15회까지 감)
- [x] 요소 하나가 실패해도 나머지가 계속 돈다
- [x] `--max-candidates`가 요소당 후보 수를 제한한다
- [ ] `method` 후보의 `gaps`에 "레지스트리 없음"이 기록된다 — 코드 경로는 있으나
      실측 실행에서 아직 `method` 후보가 안 나왔다 (에이전트가 library를 먼저 찾는다)

## 막히면
후보가 전부 `library`로만 나오면 `SEARCH_AGENT_SYSTEM_PROMPT`의 kind 3종 설명을 강화한다 —
`method`는 레지스트리가 없어 에이전트가 자연히 덜 찾는다.

승인 프롬프트가 너무 자주 뜨면 `_MAX_WEB_SEARCHES`를 줄인다. 반대로 method 후보의
근거가 부족하면 늘린다.

`create_agent`는 `checkpointer=False`로 컴파일해야 한다 — 안 주면 바깥 그래프의
`SqliteSaver`(동기 전용)를 물려받아 `ainvoke`에서 죽는다. `recursion_limit`도 호출마다
넘긴다 (그래프에 9999가 바인딩돼 있다).
