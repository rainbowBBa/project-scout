# 6단계 상세

← [문서 목록](../README.md) · 개요는 [02-파이프라인](../02-파이프라인.md)

각 파일은 같은 형식을 따른다: **목적 → 입력 → 스키마 → 동작 → 출력 → 실패 처리 → 절단 시**.

| 파일 | 단계 | LLM | 쓰는 테이블 |
|---|---|---|---|
| [0-interview.md](0-interview.md) | 막연한 요청을 되묻고 **구체화** | O | `runs` |
| [1-analyze.md](1-analyze.md) | 필요한 요소 도출 + **정말 필요한지 판단** | O | `components` |
| [2-search.md](2-search.md) | 구현 방법·소프트웨어·라이브러리 조사 + **dossier 수집** | O + MCP | `candidates` `facts` `gaps` |
| [3-verify.md](3-verify.md) | **LLM-as-judge** — 장단점 + 해결가능성, 인용 강제 | O | `verdicts` `citations` |
| [4-evaluate.md](4-evaluate.md) | 계산 점수 + judge **종합 점수** → 순위·선정 | O | `scores` `picks` |
| [5-report.md](5-report.md) | LLM 없이 **단일 HTML** 렌더링 | X | → `report.html` |

---

## 데이터가 흐르는 모양

```
                       refined_brief (구체화된 명세)
interview ──────────────────────┬──────────────────┬───────────────┐
                                │                  │               │
                                ▼                  ▼               ▼
analyze ─ 상위 3개 요소 ─▶ search ─── 후보 8~10 ──▶ verify ──▶ evaluate ──▶ report
   │         (necessity로       │        + dossier      │  판정      │  점수
   │          걸러낸 뒤)         │                      │           │
   └─ unnecessary/defer ────────┘ (search에 안 들어감)   │           │
                                                        │           │
                                        grounding.py ◀──┘           │
                                        (citations ⊆ facts)         │
                                                                    │
                    facts 숫자 ──────────────────────────────────────┘
                    (maturity·risk 계산)
```

읽는 방향으로 정리하면:

1. `interview`의 **`refined_brief`**는 `analyze` · `verify` · `evaluate` 프롬프트에
   그대로 들어간다 — 제약조건을 단계마다 재조립하지 않는다
2. `interview`의 **`non_goals`**는 `analyze`의 `defer` 판단에 직접 쓰인다
3. `analyze`가 걸러낸 요소는 `search`에 아예 들어가지 않는다 — 후보 수·토큰·시간이 함께 줄어든다
4. `search`의 **dossier**는 `verify`의 유일한 판단 재료이면서, `evaluate`의 계산 입력이다.
   같은 사실이 두 경로로 쓰이는 게 **이중 안전망**의 근거다
5. `verify`의 인용은 `grounding.py`가 `facts`와 대조한다

---

## 어느 단계에 LLM이 없는지

| 단계 | LLM | 왜 |
|---|---|---|
| `search`의 2턴(실행) | 없음 | MCP 툴 호출은 코드가 한다. LLM은 질의를 만들고 결과를 정리할 뿐 |
| `grounding.py` | 없음 | 사실 대조는 SQL이다 |
| `evaluate`의 `maturity`·`risk` | 없음 | "마지막 릴리스 1,690일 전"의 점수는 계산이지 판단이 아니다. **`overall`은 judge가 매긴다** |
| `report` | 없음 | 구조화된 `scout.db`에서 렌더링. 프롬프트 튜닝 시간을 없앤 최대 절약 |

**사실은 추론하지 않는다**는 원칙이 이 표다.
