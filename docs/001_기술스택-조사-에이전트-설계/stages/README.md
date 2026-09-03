# 6단계 상세

← [문서 목록](../README.md) · 개요는 [02-파이프라인](../02-파이프라인.md)

각 파일은 같은 형식을 따른다: **목적 → 입력 → 스키마 → 동작 → 출력 → 실패 처리 → 절단 시**.

| 파일 | 단계 | LLM | 쓰는 테이블 |
|---|---|---|---|
| [0-interview.md](0-interview.md) | 막연한 요청을 되묻고 **구체화** | O | `runs` |
| [1-design.md](1-design.md) | **구현 설계** + 결정 지점 도출 + 정말 필요한지 판단 | O + MCP | `designs` `components` |
| [2-search.md](2-search.md) | 구현 방법·소프트웨어·라이브러리 조사 + **dossier 수집** | O + MCP | `candidates` `facts` `gaps` |
| [3-verify.md](3-verify.md) | **LLM-as-judge** — 장단점 + 해결가능성, 인용 강제 | O | `verdicts` `citations` |
| [4-evaluate.md](4-evaluate.md) | 계산 점수 + judge **종합 점수** → 순위·선정 + **설계 확정** | O | `scores` `picks` `final_designs` |
| [5-report.md](5-report.md) | LLM 없이 **단일 HTML** 렌더링 | X | → `report.html` |

---

## 데이터가 흐르는 모양

```
                       refined_brief (구체화된 명세)
interview ──────────────────────┬──────────────────┬───────────────┐
                                │                  │               │
                                ▼                  ▼               ▼
design ─ 상위 3개 결정지점 ─▶ search ── 후보 8~10 ──▶ verify ──▶ evaluate ──▶ report
   │      (necessity +          │       + dossier       │  판정      │  점수
   │       needs_comparison)    │                       │           │  + 설계 확정
   ├─ unnecessary/defer ────────┘ (search에 안 들어감)    │           │
   ├─ needs_comparison=false ───┘ (이미 닫힌 결정)        │           │
   │                                                     │           │
   │                                     grounding.py ◀──┘           │
   │                                     (citations ⊆ facts)         │
   │                                                                 │
   │                 facts 숫자 ──────────────────────────────────────┤
   │                 (maturity·risk 계산)                            │
   └─ Architecture ───────────────────────────────────────────────────┘
      (기본틀 v1 — evaluate가 조사 결과로 수정해 v2로 확정한다.
       designs 행은 덮어쓰지 않는다. 두 버전의 대조가 보고서의 재료)
```

읽는 방향으로 정리하면:

1. `interview`의 **`refined_brief`**는 `design` · `verify` · `evaluate` 프롬프트에
   그대로 들어간다 — 제약조건을 단계마다 재조립하지 않는다
2. `interview`의 **`refined_brief`** 안에 범위 제외로 명시된 내용은 `design`의
   `defer` 판단에 직접 쓰인다
3. `design`이 걸러낸 결정 지점은 `search`에 아예 들어가지 않는다 — 후보 수·토큰·시간이
   함께 줄어든다. 걸러내는 축이 둘이다: **필요 없는 것**(`necessity`)과
   **이미 정해진 것**(`needs_comparison`)
4. `design`의 **`Architecture`**는 `search`를 거치지 않고 `evaluate`로 바로 간다 —
   `evaluate`가 그것을 **수정의 출발점**으로 쓴다. 확정본은 `final_designs`에 따로
   들어가고, 두 버전을 나란히 놓은 것이 보고서의 "설계가 어떻게 바뀌었나"다
5. `search`의 **dossier**는 `verify`의 유일한 판단 재료이면서, `evaluate`의 계산 입력이다.
   같은 사실이 두 경로로 쓰이는 게 **이중 안전망**의 근거다
6. `verify`의 인용은 `grounding.py`가 `facts`와 대조한다

---

## 어느 단계에 LLM이 없는지

| 단계 | LLM | 왜 |
|---|---|---|
| `search`의 **사실 추출** | 없음 | 툴은 ReAct 에이전트가 고르지만, `Fact.value`는 `ToolMessage` 원본에서 코드가 파싱한다. LLM이 쓴 문장에서 사실을 만들면 dossier가 LLM 생성물이 된다 |
| `grounding.py` | 없음 | 사실 대조는 SQL이다 |
| `evaluate`의 `maturity`·`risk` | 없음 | "마지막 릴리스 1,690일 전"의 점수는 계산이지 판단이 아니다. **`overall`은 judge가 매긴다** |
| `report` | 없음 | 구조화된 `scout.db`에서 렌더링. 프롬프트 튜닝 시간을 없앤 최대 절약 |

**사실은 추론하지 않는다**는 원칙이 이 표다.

같은 원칙의 뒷면이 하나 더 있다 — **`design`도 툴을 부르지만 그 결과는 `facts`에 넣지
않는다.** dossier는 `search`만 만든다. 설계 중에 스쳐본 값을 사실로 섞으면 kind
라우팅·top-up을 거치지 않은 사실이 dossier에 들어가, judge의 인용은 통과하는데 후보마다
근거 커버리지가 달라진다 ([1-design.md](1-design.md) "이 단계의 툴 결과는 사실이 아니다").
