# 3 · verify — LLM-as-judge

← [단계 목록](README.md) · 이전: [2-search](2-search.md) · 다음: [4-evaluate](4-evaluate.md)

**후보의 장단점과 "정말 이 요소를 해결하는지"를 판정한다.**
모듈 `scout/stages/verify.py` + `scout/grounding.py` ·
테이블 `verdicts` `citations` · LLM 8~10회 (judge)

이 단계가 이 도구의 중심이다.

---

## 목적

후보 하나를 놓고 두 질문에 답한다.

1. **정말 이 요소를 해결하는가?** (`solves_it`)
2. 장단점은 무엇인가? 조건부로만 성립하는 건 무엇인가?

판정은 **dossier에 있는 사실만 근거로** 해야 하고, 어떤 사실을 썼는지 `citations`에 남겨야 한다.

---

## 입력

후보 하나 + 그 후보의 dossier 전체 + `gaps` + 소속 요소 정보 + `interview` 제약조건.

**dossier 밖의 것은 프롬프트에 넣지 않는다.** judge가 인용할 수 있는 집합을 물리적으로 제한한다.

---

## 스키마

```python
class Verdict(BaseModel):
    candidate: str
    component: str
    solves_it: bool                # ★ "정말 이 요소를 해결하는가"
    solves_reason: str
    pros: list[str]
    cons: list[str]
    caveats: list[str]             # 조건부로만 성립하는 것
    confidence: Literal["high", "medium", "low"]
    citations: list[str]           # ★ dossier의 fact_id 만 허용
    unsupported_claims: list[str]  # judge 스스로 "근거 없는 판단"이라 표시한 항목
```

`unsupported_claims`는 judge에게 **정직할 출구를 주는** 필드다.
"근거는 없지만 경험상 이렇다"를 여기 적게 하면, 그걸 `citations`에 억지로 끼워넣지 않는다.

---

## 판정 단위 — pointwise (후보당 독립 1회)

후보 8~10개를 각각 한 번씩 판정한다. 나란히 놓고 비교하지 않는다.

| 이유 | 설명 |
|---|---|
| 원래 개별 질문이다 | "정말 해결하는가"는 다른 후보와 무관하게 답할 수 있다 |
| 순서 편향이 없다 | 후보를 나열하면 제시 순서가 결과를 바꾼다 — LLM-as-judge의 알려진 약점 |
| 재판정 범위가 작다 | 후보 하나가 바뀌면 그것만 다시. 배치는 전체 재판정 |
| 벽시계 시간이 비슷하다 | 병렬로 돌리므로 호출 수가 많아도 오래 걸리지 않는다 |
| 프롬프트가 짧다 | dossier 하나만 들어간다 |

후보 간 상대 비교는 `evaluate`가 맡는다. **판정과 비교를 분리한다.**

동시성은 `Semaphore(4)`. Bedrock 동시 호출 쿼터가 낮으면 조인다
([07-검증](../07-검증.md) M0 확인 항목 2번).

---

## grounding check — judge의 유일한 실질적 안전장치

LLM-as-judge의 실패 모드는 **없는 사실을 지어내는 것**이다. 대응은 코드다.

```
1. citations LEFT JOIN facts  →  NULL인 행 = dossier에 없는 id를 인용한 것
2. 위반이 있으면 위반 목록을 프롬프트에 넣어 1회 재판정
3. 2차에도 위반 → confidence "low" 강등 + verdicts.grounding_violations 기록
4. citations가 비었으면 → confidence 강등. 근거 0개 판정은 판정이 아니다
```

쿼리 본체는 [03-저장](../03-저장.md)에 있다. 30줄이면 되고,
**이게 없으면 LLM-as-judge를 신뢰할 근거가 없다.**

`test_grounding.py`가 이 장치를 검증한다 — dossier에 없는 id를 인용한 `Verdict`를 손으로
주입해 잡히는지 본다. LLM을 부르지 않으므로 빠르고 결정론적이다.

---

## 관대함 편향 대응 — 앵커 루브릭

judge는 대체로 후하게 준다. 프롬프트에 결정론적 앵커를 박는다.

```
solves_it = false 로 판정해야 하는 경우:
  - dossier에 요소 요구사항을 충족한다는 근거가 없음
  - gh.archived 가 true 이거나 npm.deprecated 가 true
  - 요구 규모/제약과 명백히 불일치 (근거를 인용해 설명)

confidence = "low" 로 판정해야 하는 경우:
  - dossier_gaps 가 핵심 항목을 포함
  - 인용 가능한 사실이 2건 이하

citations 규칙:
  - dossier에 있는 fact_id 만 쓴다. 없는 id를 쓰면 재판정된다
  - 근거 없는 판단은 citations 대신 unsupported_claims 에 적는다
```

`solves_it` 자체가 앵커의 효과를 크게 받는다. 앵커 없이 물으면 judge는 거의 모든 후보에
`true`를 준다.

---

## 판정 예시

```
socket.io  solves_it = true   confidence = high
  solves_reason: "재연결·룸·폴백을 내장해 요소 요구를 직접 충족"
  pros: ["재연결 자동", "룸 개념 내장", "폴백(long-polling) 지원"]
  cons: ["독자 프로토콜이라 표준 WebSocket 클라이언트와 호환 안 됨"]
  caveats: ["수평 확장 시 어댑터(Redis 등) 별도 필요"]
  citations: [npm.last_release, gh.last_commit, gh.contributors, osv.vulns]

sockjs     solves_it = false  confidence = high
  solves_reason: "마지막 릴리스 2021-01-14(1,690일 전), 마지막 커밋 3년 전 —
                  유지보수가 중단된 것으로 판단"
  citations: [npm.last_release, gh.last_commit]

이벤트 소싱  solves_it = true   confidence = low
  solves_reason: "메시지 저장 요소를 해결할 수 있으나 근거가 웹 스니펫 3건뿐"
  caveats: ["3인 팀 3개월에는 구현·운영 부담이 큼"]
  citations: [web.1, web.2]
  unsupported_claims: ["구현 난이도 추정은 dossier 근거 없음"]
```

---

## 출력

```sql
verdicts  (slug, candidate, solves_it, solves_reason, confidence,
           pros_json, cons_json, caveats_json, grounding_violations)
citations (slug, candidate, fact_id)
```

`pros`/`cons`/`caveats`는 조회 조건으로 쓰지 않으므로 JSON 컬럼에 그대로 담는다.
`citations`는 조인 대상이므로 정규화한다.

---

## 실패 처리

| 상황 | 동작 |
|---|---|
| grounding 위반 1차 | 위반 목록을 넣어 1회 재판정 |
| grounding 위반 2차 | `confidence: low` 강등 + `grounding_violations` 카운트 기록 |
| `citations` 비어 있음 | `confidence` 강등 |
| 구조화 출력 파싱 실패 | `include_raw=True`로 원본 확보 후 1회 재시도. `Verdict`는 필드가 많아 여기가 가장 위험한 지점이다 |
| Bedrock 스로틀링 (429) | SDK 재시도 + `Semaphore` 축소 |
| 후보 하나의 판정이 끝내 실패 | 그 후보를 `solves_it=false`, `confidence=low`, 이유 "판정 실패"로 기록하고 계속 |

---

## 절단 시

**절단선 3번** — 재판정 루프(위 2단계)를 생략하고 검출·표시만 한다.

**grounding 검출 자체는 절단하지 않는다.** 검출이 사라지면 judge를 신뢰할 근거가 없어지고,
그러면 이 도구는 그냥 LLM에게 물어보는 것과 같아진다.

잘라낸 것 중 이 단계와 관련된 것:

- **judge 다수결(self-consistency)** — 후보당 3회 판정해 다수결. 일관성이 가장 높지만
  호출이 24~30회가 된다. 구조는 잡아두고 상수만 바꾸면 되게 한다
- **listwise 비교 judge** — 요소별로 후보를 나란히 놓고 한 번에 판정.
  호출 수는 1/3이지만 순서 편향이 생긴다. pointwise + `evaluate` 비교로 대체
