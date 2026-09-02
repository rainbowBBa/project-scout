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
| [05](STEP-05-search.md) | 후보 발견 + dossier 수집 | 1.5h | O |
| [06](STEP-06-verify.md) | LLM-as-judge + grounding | 1.25h | — |
| [07](STEP-07-evaluate.md) | 점수 계산 + judge 종합 점수 · 순위 | 1h | — |
| [08](STEP-08-report.md) | 단일 HTML 렌더링 | 1.25h | — |
| [09](STEP-09-검증.md) | 테스트 4종 + E2E | 1h | — |
| [10](STEP-10-선택.md) | `osv` · `method` 후보 (여유 시) | 여유분 | O |

**Day 1** STEP 00~04 앞부분 (8h) · **Day 2** STEP 04 마무리~09 (7.25h + 여유 1h)

---

## 왜 MCP 서버가 4번인가

001은 Day 1에 MCP 서버를 먼저 만들라고 했다. 순서를 바꾼 근거는 **의존성**이다 —
`interview`와 `analyze`는 LLM만 쓰고 MCP가 필요 없다. MCP는 `search`부터 필요하다.

```
STEP 0 환경 → 1 저장 → 2 interview → 3 analyze → 4 MCP서버 → 5 search → …
                          └── MCP 없이 돌아감 ──┘   └ 여기서 필요해짐
```

**리스크**: 사내 인터넷 출구가 막히는지 확인이 STEP 4까지 늦어진다.
→ STEP 00에 **MCP 스모크 30분**을 넣어 "밖으로 나갈 수 있는가"만 첫날에 답한다.

**비용**: MCP 서버가 Day 2로 일부 넘어와 Day 2가 빡빡해진다.
→ STEP 04의 providers를 5종 → **4종**으로 줄였다. `osv`는 001의 절단선 1번이므로
처음부터 STEP 10으로 뺐다 (6.5h → 5h).

---

## 진행 체크리스트

```
Day 1
[x] STEP 00  환경        uv sync · .env/Settings · doctor · MCP 스모크
[x] STEP 01  저장        scout.db 8개 테이블 생성
[ ] STEP 02  interview   scout run 이 되묻고 runs 행 생성
[ ] STEP 03  analyze     components 6~10행 + necessity 분류
[ ] STEP 04  MCP 서버    egress · cache · providers (진행 중)

Day 2
[ ] STEP 04  MCP 서버    providers 4종 완료 · 단독 호출 확인
[ ] STEP 05  search      candidates/facts/gaps 채워짐
[ ] STEP 06  verify      verdicts/citations + test_grounding 통과
[ ] STEP 07  evaluate    scores 3기준 + overall + score_reason + margin
[ ] STEP 08  report      브라우저에서 열리는 report.html
[ ] STEP 09  검증        테스트 4종 + E2E 완주
[ ] STEP 10  선택        여유 있으면 osv
```

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
