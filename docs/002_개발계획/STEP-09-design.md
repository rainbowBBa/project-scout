# STEP 09 · design

> `analyze`를 `design`으로 대체한다. 구현 설계를 세우고 비교가 필요한 결정 지점을 뽑는다.
> STEP 03에서 만든 요소 도출을 **설계 도출로 바꾸는 단계**다.

**선행** STEP 08 · **시간** ~3h · **설계** [stages/1-design](../001_기술스택-조사-에이전트-설계/stages/1-design.md) · [CHANGELOG v20](../001_기술스택-조사-에이전트-설계/CHANGELOG.md)

이 STEP은 쪼갤 수 없다. 스키마·테이블·프롬프트·노드 이름이 한꺼번에 바뀌므로
중간 지점에서는 `scout run`이 돌지 않는다.

## 만들 것

### 1. 공유 모듈 추출 (먼저 한다 — 기존 테스트로 안전망을 확인하고 넘어간다)

`design`과 `search`가 같은 장치를 쓴다. stage → stage import를 만들지 않는다.

- `scout/approval.py` ← `stages/search.py`에서 이동:
  `Approval` · `Approve` · `NonInteractive` · `APPROVAL_NOTICE` · `default_approve` ·
  `auto_approve` · `SearchGate` · `wrap_web_search`
- `scout/agentkit.py` ← `stages/search.py`에서 이동:
  `ToolCall` · `message_text` · `parse_payload`(현 `_parse_payload`) ·
  `collect_tool_calls` · `build_transcript`
- `stages/search.py` — 두 모듈에서 import. 동작은 그대로
- `cli.py` — `search_stage.auto_approve` → `approval.auto_approve`
- `tests/test_search_approval.py` — import 경로만 갱신 (검사 내용은 그대로)

### 2. 스키마 · 저장

- `scout/schemas.py` — `Architecture` 신설, `Component` 필드 교체
  (`why` → `role_in_design`, `+ decision_question` `+ constraints`
  `+ needs_comparison` `+ no_comparison_reason`), `Analysis` → `Design`
- `scout/store.py` — `designs` 테이블 신설 · `components` 컬럼 교체
  (`search_hints_json` 포함) · `upsert_design` / `get_design`
- `scout/state.py` — `+ architecture`

### 3. 프롬프트

- `scout/prompts.py` — `ANALYZE_*` 삭제, 신설:
  `DESIGN_AGENT_SYSTEM_PROMPT` · `DESIGN_AGENT_TASK_PROMPT` ·
  `DESIGN_EXTRACT_SYSTEM_PROMPT` · `DESIGN_EXTRACT_PROMPT` · `DESIGN_EXTRACT_RETRY_HINT`
- `SEARCH_AGENT_TASK_PROMPT`에 `decision_question` · `constraints` 주입

기존 `ANALYZE_SYSTEM_PROMPT`에서 **살려서 옮길 것** (버리면 회귀한다):

```
kind 5종 각각 최소 하나 검토 + 흔히 빠뜨리는 것 목록
  (인증 · 마이그레이션 · 관측 · 비용 모니터링 · 레이트리밋 · LLM 캐싱)
necessity 4단계 앵커 + "전부 essential이면 잘못된 것"
necessity_reason 에 제약조건 숫자 인용 요구
name 기술 중립 (편향 방지)
```

새로 박을 앵커 3개:

```
1. search_hints 는 영어 기술 어휘로 쓴다. 비면 안 된다
   ["실시간 메시지 전달"]  ✘   요소 이름 복사
   ["socket.io", "ws websocket library node", "server-sent events chat"]  ✔
2. needs_comparison=false 의 조건을 반례로 (언어·런타임이 refined_brief 에
   이미 정해진 경우 등) — 안 쓰면 전부 true 로 준다
3. 사실 수치를 설계 문장에 쓰지 마라 — 숫자 확인은 search 의 일
```

### 4. 단계 · 배선

- `scout/stages/design.py` — `analyze.py` 대체. 2-pass
  (`create_agent` → `invoke_structured`), `approve`를 받는다,
  `wrap_web_search(..., budget=3)`, `select_passing_components`에
  `needs_comparison` 필터 추가
- 툴 루프는 `recursion_limit=10`(superstep 수 — 툴 호출 4~5회). `ainvoke`가 아니라
  `astream`으로 돌려 한도 초과(`GraphRecursionError`) 시 **부분 기록을 살린다**
- `scout/graph.py` — 노드 `analyze` → `design`, 엣지 2개
- `scout/cli.py` — `STAGE_ORDER` · `IMPLEMENTED_STAGES` · `STAGE_LABELS`(`"design": "설계"`) ·
  `Stage`/`ShowStage` enum · `_print_stage_summary`의 분기 · `show` 출력

## 완료 기준

> **상태 (2026-09-03)** — 코드는 완성됐고 커밋됐다(`fecef01`). 표시가 `[~]`인 항목은
> **부분 근거만 있고** 저장까지 확인하지 못한 것이고, `[ ]`는 E2E가 필요한 것이다.
> E2E는 `design`의 구조화 출력 파싱에서 한 번 죽었다 — 원인은 이 STEP의 코드가 아니라
> `invoke_structured`가 첫 `tool_call`만 보는 것이었다(아래 "막히면" 참고).

- [x] `uv run pytest` — 기존 4종이 그대로 통과한다 (공유 모듈 추출이 아무것도 깨지 않았다)
      → **34개 통과** (기존 28 + `test_llm_cache` 6)
- [ ] `uv run scout run "사내 200명이 쓰는 AI 요약 팀 채팅 앱, 3인 TypeScript 팀, 3개월" --stop-after design --auto-approve-search` 가 완주한다
      → 1회차 `RuntimeError: Design 구조화 출력 파싱 실패`. 파서 수정 후 재실행 확인 대기
- [ ] `scout show <slug> design` 에 **`Architecture` 본문**이 있다 —
      `shape` · `data_flow` · `build_order` 가 비어 있지 않다
- [~] **통과한 결정 지점의 `search_hints`가 전부 비어 있지 않고 영어 기술 어휘다** —
      요소 이름을 그대로 복사한 것이면 실패
      → 응답 원본에서 확인됨: `['socket.io', 'ws websocket library node',
        'websocket reconnection room …']` · `['redis cache', 'ioredis typescript', …]` ·
        `['docker nodejs', 'github actions deploy', 'railway vercel render', …]`.
        에이전트의 `npm_search` 질의도 영어였다(`ORM TypeScript PostgreSQL prisma
        typeorm` 등). **DB 저장까지 확인은 재실행 대기**
- [ ] `decision_question` 이 "무엇을 정해야 하는가"의 형태다 (`role_in_design`의 복사가 아니다)
- [ ] `constraints` 가 `refined_brief`의 제약(인원·기간·기술)을 근거로 든다
- [ ] `needs_comparison=false` 가 최소 1개 나오고 `no_comparison_reason`이 채워진다
- [ ] `necessity` 가 `defer`/`unnecessary`를 최소 1개 낸다 (STEP 03에서 지키던 기준)
- [~] `designs` 1행 + `components` 6~10행이 저장된다. 걸러진 것도 전부 남는다
      → **테이블 10개가 실제 DB에 생성됨**(`designs` 포함) · `store` 왕복과 통과 필터
        2축(`necessity` + `needs_comparison`)을 스모크로 확인. 행 채움은 재실행 대기
- [ ] `web_search` 승인 프롬프트가 **최대 3번**까지만 뜬다
      → 1회차에서 에이전트가 `npm_search`만 썼다 — 웹검색 경로는 아직 안 타봤다
- [ ] `--auto-approve-search` 없이 전부 거부해도 설계가 나온다 (레지스트리 + LLM 지식만으로)
- [x] `uv run ruff check` 통과

## 막히면

**기존 DB를 못 읽는다** — `components` 컬럼이 바뀌었고 `store.py`는
`CREATE TABLE IF NOT EXISTS`만 실행한다. 마이그레이션을 만들지 말고 **새 slug로 돌린다**
(설명을 바꾸거나 `runs/<slug>/`를 지운다).

**`checkpointer=False`를 빼먹으면** 바깥 그래프의 `SqliteSaver`(동기 전용)를 물려받아
`ainvoke`에서 터진다 (`search`와 같은 함정).

**`SearchGate`를 노드 간에 공유하지 않는다** — `design_node`와 `search_node`가 각각
`asyncio.run()`으로 루프를 새로 열기 때문에 `asyncio.Lock`이 다른 루프에 묶인다.
각자 만든다. 그 이유를 코드 주석으로 남긴다.

**`search_hints`가 비어서 나오면** 프롬프트 앵커부터 본다. 예시를 실패/성공 쌍으로
보여주지 않으면 LLM이 요소 이름을 복사한다. 그게 이 STEP의 존재 이유이므로
"나중에 고치자"로 넘기지 않는다.

**설계 산문이 길어지는 걸 참는다** — `Architecture.summary`는 3~5문장이다.
길이가 늘면 `evaluate`의 설계 확정 프롬프트가 재료에 파묻힌다.

**`Design 구조화 출력 파싱 실패`가 나면 프롬프트를 의심하기 전에 `tool_call` 개수를 본다.**
실측에서 모델이 한 응답에 `tool_use` 블록을 **두 개** 냈고, `with_structured_output`의
파서는 `first_tool_only=True`라 **첫 블록만** 본다 — 첫 블록이 불완전하면 같은 응답에
완전한 블록이 있어도 전체가 실패한다. `Design`처럼 필드가 많은 스키마에서 특히 난다.
`llm.py`의 `_salvage`가 재시도 전에 나머지 블록을 훑어 구제하고, 실패 시 `parsing_error`를
메시지에 붙인다. 그게 없으면 원인 진단이 로그 고고학이 된다.
