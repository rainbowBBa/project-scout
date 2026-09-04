# 002 · 개발계획

> 파이프라인이 순차적이므로 `interview`부터 하나씩 만든다.
> STEP이 끝날 때마다 `scout run`이 실제로 돈다.

설계는 [001](../001_기술스택-조사-에이전트-설계/README.md) · 실행 순서는 이 폴더

---

## STEP 목록

| STEP | 내용 | 시간 | MCP 필요 |
|---|---|---|---|
| [00](STEP-00-환경.md) | uv 워크스페이스 · `.env`/`Settings` · `doctor` · MCP 스모크 | 1.5h | 스모크만 |
| [01](STEP-01-저장.md) | `schemas` · `store` · `state` | 1h | — |
| [02](STEP-02-interview.md) | 요청 구체화 → `refined_brief` | 1h | — |
| [03](STEP-03-analyze.md) | 요소 도출 + `necessity` | 1h | — |
| [04](STEP-04-mcp서버.md) | `egress` · `cache` · providers 4종 | 3.5h | **만든다** |
| [05](STEP-05-search.md) | 후보 발견 + dossier 수집 (ReAct + 웹검색 승인) | 2h | O |
| [06](STEP-06-verify.md) | LLM-as-judge + grounding | 1.25h | — |
| [07](STEP-07-evaluate.md) | 점수 계산 + judge 종합 점수 · 순위 | 1h | — |
| [08](STEP-08-report.md) | 단일 HTML 렌더링 | 1.25h | — |
| [09](STEP-09-design.md) | **`analyze` → `design`** — 구현 설계 + 결정 지점 | 3h | O |
| [10](STEP-10-설계확정.md) | `evaluate` 끝에서 권장 설계 확정 | 1.25h | — |
| [11](STEP-11-권장설계리포트.md) | 보고서 최상단을 권장 설계로 | 1h | — |
| [12](STEP-12-검증.md) | 테스트 6종 + E2E | 1.5h | O |
| [13](STEP-13-선택.md) | `osv` · `method` 후보 · `--from` (여유 시) | 여유분 | O |

**Day 1** STEP 00~04 앞부분 (8h) · **Day 2** STEP 04 마무리~08 (6.25h)
· **Day 3** STEP 09~12 (6.75h)

---

## 왜 09부터 다시 시작하는가

STEP 08까지 파이프라인이 완주하는 상태에서 결과를 보고 뒤집은 판단이다.
`analyze`의 산출물이 추상적인 요소 목록이라 `search`가 후보를 잘 못 찾고, 보고서가
"요소별로 이걸 골랐다"에서 멈췄다. 근거와 경위는
[001 CHANGELOG v20](../001_기술스택-조사-에이전트-설계/CHANGELOG.md).

```
STEP 03  analyze   요소 도출 + necessity          ← 끝낸 작업. 기록으로 남긴다
   ↓
STEP 09  design    구현 설계 + 결정 지점           ← 03을 대체한다
STEP 10  확정      요소별 승자 → 하나의 설계
STEP 11  리포트     최상단이 "이렇게 만들면 되겠다"
STEP 12  검증      테스트 6종 (5종 + test_design_no_facts)
```

STEP 03~08 문서는 **고치지 않는다.** 끝낸 작업의 기록이고, 무엇이 바뀌었는지는
09~12와 001 CHANGELOG가 말한다.

**단계 수는 6개 그대로다** — `design`은 `analyze`가 있던 자리를 대체하고,
설계 확정은 `evaluate` 안에 들어간다. 7번째 단계를 만들지 않았다.

---

## 왜 MCP 서버가 4번인가

001은 Day 1에 MCP 서버를 먼저 만들라고 했다. 순서를 바꾼 근거는 **의존성**이다 —
`interview`와 `analyze`는 LLM만 쓰고 MCP가 필요 없다. MCP는 `search`부터 필요하다.

> 이 근거는 STEP 09에서 반쯤 뒤집혔다 — `design`은 툴을 쓰므로 MCP가 필요하다.
> 그때는 MCP 서버가 이미 있으므로 순서에는 영향이 없다.

```
STEP 0 환경 → 1 저장 → 2 interview → 3 analyze → 4 MCP서버 → 5 search → …
                          └── MCP 없이 돌아감 ──┘   └ 여기서 필요해짐
```

**리스크**: 사내 인터넷 출구가 막히는지 확인이 STEP 4까지 늦어진다.
→ STEP 00에 **MCP 스모크 30분**을 넣어 "밖으로 나갈 수 있는가"만 첫날에 답한다.

**비용**: MCP 서버가 Day 2로 일부 넘어와 Day 2가 빡빡해진다.
→ STEP 04의 providers를 5종 → **4종**으로 줄였다. `osv`는 001의 절단선 1번이므로
처음부터 선택 STEP(현 [13](STEP-13-선택.md))으로 뺐다 (6.5h → 5h).

---

## 진행 체크리스트

```
Day 1
[x] STEP 00  환경        uv sync · .env/Settings · doctor · MCP 스모크
[x] STEP 01  저장        scout.db 8개 테이블 생성
[x] STEP 02  interview   scout run 이 되묻고 runs 행 생성
[x] STEP 03  analyze     components 6~10행 + necessity 분류
[x] STEP 04  MCP 서버    egress · cache · providers (완료)

Day 2
[x] STEP 04  MCP 서버    providers 4종 완료 · 단독 호출 확인
[x] STEP 05  search      ReAct 에이전트 + 웹검색 승인 게이트 · candidates/facts/gaps 채워짐
[x] STEP 06  verify      verdicts/citations + test_grounding 통과
[x] STEP 07  evaluate    scores 3기준 + overall + score_reason + margin
[x] STEP 08  report      브라우저에서 열리는 report.html

Day 3 — analyze → design 재설계 (001 CHANGELOG v20~v22)
[~] STEP 09  design      코드 완료 fecef01 · E2E 완주 · Architecture·search_hints(영어)·
                          constraints·needs_comparison 확인 · necessity 걸러내기만 미확인
[~] STEP 10  설계확정     코드 완료 5b55985 · E2E 완주 · final_designs 1행 · v1≠v2 대조 성립
                          integration_notes·combination_risks 확인 · changes_from_design 미확인
[x] STEP 11  리포트       최상단 권장 설계 · v1↔v2 대조 · "이미 정해진 부분" · CDN 0
[~] STEP 12  검증        테스트 6종 전부 존재 · pytest 94개 통과 · 격리 두 겹 실측
                          (TID251 3건 검출 · MCP 단독 sync에 langchain 0) ·
                          E2E 완주와 육안 확인만 미실행
[~] STEP 13  선택        osv_query 되돌림 완료 (001 v28) · 재판정 루프는 STEP 06에서
                          이미 끝나 있었다 · method 후보 · --from · 풀 규모가 남았다

[~] = 배선은 E2E로 확인됐고 **판단 품질만** 남았다 — 아래 참고
```

### STEP 09·10·12가 `[~]`인 이유 — 판단 품질은 정본 모델에서 본다

E2E는 완주한다(`report.html`까지). 남은 것은 **작은 모델로는 확인할 수 없는 항목**이다.

아래 흔들림 셋은 쿼터 때문에 임시로 Haiku를 쓰던 동안 실측된 것이다. 성격이 다르다.

> **모델은 `us.anthropic.claude-sonnet-4-6`으로 돌아왔다.** `doctor`로 실측한 결과
> `anthropic.claude-sonnet-5`는 쿼터가 아니라 **이 계정에 entitlement가 없고**
> (`AccessDeniedException`), `anthropic.claude-sonnet-4-6`은 on-demand가 안 돼
> 크로스리전 프로파일(`us.` 접두사)이 필요하다. `config.py`의 기본값은 아직
> `anthropic.claude-sonnet-5`라 이 계정에서는 `.env`가 있어야 돈다.

| 증상 | 성격 | 처리 |
|---|---|---|
| 한 객체를 `tool_use` 두 블록으로 쪼갬 | 형식 | `llm.py` `_salvage`가 병합해 흡수 (`a32745a`) |
| 리스트 자리에 의사 XML 문자열 | 형식 | `schemas.py` `StrList`가 태그 경계로 쪼갠다 |
| `necessity`/`needs_comparison` 혼동 · `changes_from_design` 누락 | **판단** | **흡수하지 않는다** — `gaps`에 기록하고 Sonnet에서 다시 본다 |

형식은 흡수한다 — 흔들림 하나가 후보를 통째로 탈락시켜 조사 결과를 지우기 때문이다.
판단은 흡수하지 않는다 — 프롬프트를 작은 모델에 맞춰 휘면 `necessity`의 이중 축(이
도구의 차별점)이 모델에 종속되고, 정본 모델로 돌아왔을 때 그 왜곡이 남는다.
자세한 구분은 [08-설정](../001_기술스택-조사-에이전트-설계/08-설정.md)
"SCOUT_MODEL_ID".

**쿼터가 회복되면 Sonnet으로 한 번 돌려** STEP 09·10의 남은 항목과 STEP 12의 육안
확인을 함께 본다 — `SCOUT_LLM_CACHE`는 모델이 바뀌면 키가 갈리므로 캐시가 새로 채워진다.

STEP 12는 성격이 조금 다르다 — **LLM을 부르지 않는 항목은 전부 끝났다** (테스트 6종 ·
격리 두 겹). 남은 것은 E2E 완주와 판단 품질 육안 확인 6항목이고, 그게 09·10의 잔여
항목과 같은 실행에서 보이는 것들이다. 그래서 세 STEP이 한 번의 Sonnet 실행으로 함께
닫힌다.


---

## STEP 문서 읽는 법

각 파일은 같은 형식이다.

| 항목 | 뜻 |
|---|---|
| 상단 인용 블록 | 이 STEP이 하는 일 (2줄) |
| **선행** | 이것부터 끝나 있어야 한다 |
| **설계** | 001의 해당 문서 링크. 스키마·이유는 거기 있다 |
| 만들 것 | 새로 만들거나 고칠 파일 |
| 완료 기준 | 실행하면 참/거짓이 판별되는 체크박스 |
| 막히면 | 이 STEP에서 가장 자주 걸릴 지점 |

**설계 근거는 이 폴더에 중복하지 않는다.** 왜 그렇게 하는지는 001을 본다.
