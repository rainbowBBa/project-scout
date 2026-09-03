# 4 · evaluate

← [단계 목록](README.md) · 이전: [3-verify](3-verify.md) · 다음: [5-report](5-report.md)

**계산된 숫자와 판정을 놓고 종합 점수를 매기고 요소별 순위를 정한다.**
모듈 `scout/stages/evaluate.py` + `scout/rubric.py` ·
테이블 `scores` `picks` · LLM 1회/요소 (요소 3개면 3회)

---

## 목적

`verify`가 후보를 하나씩 판정했다. 이제 **후보끼리 비교**해 요소별 1위를 고르고
최종 스택을 조립한다.

`verify`가 판정을 끝냈으므로 **`evaluate`는 사실을 다시 해석하지 않는다.**
같은 사실을 두 번 추론하면 두 결론이 갈릴 수 있고, 그러면 어느 쪽을 믿어야 할지 알 수 없다.

---

## 입력

| 입력 | 출처 |
|---|---|
| 판정 | `verdicts` + `citations` |
| 계산된 점수 | `scores` (`maturity` · `risk`) |
| 사실 숫자 | `facts` (SQL로 직접 조회) |
| 제약조건 | `runs.interview_json` → **`refined_brief`** |

---

## 동작

### 1. 탈락 처리

`solves_it == False`인 후보는 탈락. `solves_reason`을 그대로 `picks.rejected_reason`에 인용한다.
새로 이유를 만들지 않는다 — judge가 이미 근거와 함께 판정했다.

### 2. 계산 점수 — 2기준, 코드가 한다

| 기준 | 산출 | `scores.source` |
|---|---|---|
| `maturity` | dossier 숫자로 **코드가 계산** | `computed` |
| `risk` | dossier 숫자로 **코드가 계산** | `computed` |

이 두 숫자는 **judge 프롬프트에 그대로 들어간다.** 아래 3번의 이중 안전망 경로다.

숫자가 없는 후보(`method` 등)는 계산할 수 없으므로 `score = NULL`,
`source = "unavailable"`로 기록한다. **없는 걸 추측하지 않는다.**

### 3. 종합 점수 + 순위 — LLM 1회/요소

요소 하나의 통과 후보 전체를 놓고 **`overall` 점수를 매기고** 순위를 낸다.

```
입력:  refined_brief
     + 그 요소의 Component (why · approach_notes)
     + 통과 후보들의 Verdict 전체 (solves_reason · pros · cons · caveats · confidence)
     + 계산된 maturity · risk 점수      ← ★ 숫자로 프롬프트에 들어간다

출력:  ElementPick
```

```python
class CandidateScore(BaseModel):
    candidate: str
    overall: int          # 1~5, judge — 유일한 LLM 점수
    score_reason: str     # ★ 이 점수를 매긴 이유. fact_id 또는 verdict 를 인용한다

class ElementPick(BaseModel):
    component: str
    scores: list[CandidateScore]   # 통과 후보 전원
    ranking: list[str]             # overall 내림차순. 동점은 maturity → 이름 순
    winner: str
    winner_reason: str             # ★ 제약 인용 + 2위와의 점수 차이
    runner_up_note: str
    margin: Literal["decisive", "close"]   # 1위·2위 차이
```

최종 스택은 요소별 `winner`의 모음이다.

#### 왜 LLM 점수를 하나만 두는가

`fit`·`team_fit`을 따로 매기게 하면 **judge가 그것들을 평균해 `overall`을 낼 유혹이 커진다.**
하나만 매기게 하면 그 위험 자체가 사라진다.

그리고 **`score_reason` 한 문장이 숫자 두 개보다 정보가 많다.**
"요구 충족은 되지만 팀에 낯설다"는 `fit=5, team_fit=2`보다 읽는 사람에게 유용하다.
부수 효과로 리포트 막대가 3개라 읽힌다 — 5개는 눈이 따라가지 못한다.

#### ★ `overall`은 `maturity`·`risk`의 평균이 아니다

산술 평균으로 내면 그건 다시 계산이고, 가중치 없는 가중 합산일 뿐이다.
judge가 **판단해야** 한다. 프롬프트에 반례를 박는다.

```
overall 은 maturity·risk 의 평균이 아니다. 판단해서 매긴다.
  - maturity 5 라도 요소 요구를 못 채우면 overall 은 2 다
  - 요구를 완벽히 채워도 risk 1 이면 overall 은 2 를 넘지 않는다
  - maturity 가 unavailable 이면 그 사실을 근거로 overall 을 낮춘다
  - refined_brief 의 제약(팀 숙련 언어 · 데드라인 · 예산)이 overall 에 반영돼야 한다
```

#### `score_reason` — 후보마다 왜 그 점수인지

```
socket.io   overall 4
  "npm.last_release 11일 전이고 재연결·룸이 내장돼 3인 팀이 3개월에 붙이기 쉽다.
   독자 프로토콜이라 표준 클라이언트와 못 붙는 점이 5를 막았다."

ws          overall 3
  "maturity 4 로 안정적이지만 재연결·룸을 직접 구현해야 해 3개월 일정에 부담이다."

이벤트 소싱  overall 2
  "maturity 가 unavailable 이고 근거가 웹 스니펫 3건뿐이다.
   3인 팀 3개월에 운영 부담이 크다."
```

`maturity`·`risk`도 `scores.reason`을 갖는다 — 계산 근거 요약
(`"npm.last_release 11일 전, gh.contributors 42명 → 5"`).
보고서에서 계산된 점수도 왜 그 값인지 보여줄 수 있다.

#### `margin` — 순위만으로는 못 하던 것

```
overall 차이 >= 2  →  "decisive"
overall 차이 <= 1  →  "close"
```

이건 뺄셈이지 판단이 아니다. **코드가 계산해 judge가 채운 `margin`을 덮어쓴다** —
`ElementPick`에 필드를 둔 건 judge가 1·2위 차이를 의식하고 `winner_reason`을 쓰게
하려는 것이지, 그 값을 믿으려는 게 아니다. 통과 후보가 1개면 `decisive`다.

`close`면 보고서에 **"근접 — 2위도 합리적 선택"**을 표시한다.
"1위가 socket.io"와 "socket.io 4 vs ws 3"은 의사결정에서 완전히 다른 정보다.
후보가 2~3개뿐인 프로토타입 규모에서 특히 값어치 있다.

#### `winner_reason`에 들어가야 하는 것 두 가지

```
1. refined_brief 의 제약 인용
2. 2위와의 점수 차이
```

> "socket.io를 골랐다. `overall` 4 vs ws 3 — 재연결·룸이 내장돼 3인 팀 3개월에
> 구현 부담이 작다."

---

## 왜 가중 합산이 아니라 judge인가

이전 설계는 5기준에 가중치를 곱해 합산했다. 가중치는 `interview`가 제약조건에서 도출했다
(데드라인 ≤ 3개월이면 `team_fit ×1.5` 같은 규칙). **프로토타입에서 뺐다.**

| 문제 | 설명 |
|---|---|
| 배수의 근거가 임의적 | 왜 1.5이고 1.3이 아닌가. 튜닝할 시간이 없다 |
| 대응 항목이 없는 제약이 갈 곳을 잃음 | 예산은 5기준 중 어디에도 대응하지 않았다 |
| 같은 정보를 두 번 해석 | `fit`·`team_fit`·`exit_cost` 점수의 재료가 이미 `verify`의 `pros`/`cons`/`caveats`에 다 있었다 |

judge는 제약조건 문단을 직접 읽고 `overall`을 매긴다. "3인 팀이 3개월에 출시해야 하므로
학습 곡선이 낮은 쪽"처럼 **사람이 하는 판단을 그대로 한다.**

점수는 유지하되 **만드는 방식이 다르다** — 곱하고 더하지 않고, 근거를 보고 매긴다.

`winner_reason`에 `refined_brief`의 제약이 인용되지 않으면 판단에 근거가 없는 것이다 —
`verify`의 앵커 루브릭과 같은 방식으로 프롬프트에 요구한다.

---

## 왜 `maturity`·`risk`만 코드로 남겼나

**"마지막 릴리스 1,690일 전"의 성숙도 점수는 계산이지 판단이 아니다.**

그리고 이게 `test_stale_regression`이 검증할 수 있는 형태다 —
**judge가 낡은 사실을 무시해도 `evaluate`의 계산이 잡아낸다.**

```
             verify (judge)          evaluate (계산)
sockjs   →   solves_it=false   또는   maturity=1
             ↓                        ↓
             둘 중 하나만 작동해도 최종 순위에서 탈락한다
```

이게 **판정과 계산의 이중 안전망**이다. 둘 다 실패해야 잘못된 추천이 나온다.
가중 합산은 없앴지만 이 성질은 지켰다 — 계산된 점수가 judge 프롬프트에 숫자로 들어간다.

---

## 점수 공식 (`rubric.py`)

### `maturity` — 1~5

```
릴리스 최근성   npm.last_release / pypi.last_release 경과일
                  ≤ 90일 → 5   ≤ 365일 → 4   ≤ 730일 → 3   ≤ 1095일 → 2   그 이상 → 1
커밋 활성      gh.last_commit 경과일 (같은 구간)
기여자 수      gh.contributors    ≥ 10 → 5   ≥ 5 → 4   ≥ 3 → 3   ≥ 2 → 2   1 → 1
archived       gh.archived = true → 무조건 1

→ 세 값의 최소값을 취한다 (가장 약한 신호가 성숙도를 결정한다)
```

최소값을 쓰는 이유: 별이 5만 개라도 3년째 커밋이 없으면 성숙한 게 아니다.
평균을 쓰면 강한 신호가 약한 신호를 가린다.

신호가 일부만 있으면 **있는 신호만의 최소값**을 취한다 — 없는 신호를 5로도 1로도
채우지 않는다. 없는 것을 5로 채우면 조회 실패가 좋은 점수로 둔갑하고, 1로 채우면
`gh` 사실이 없는 후보가 전부 최하점이 된다. 셋 다 없으면 계산하지 않고
`unavailable`이다 (`method` 후보가 이 경우다).

### `risk` — 1~5 (높을수록 안전)

```
취약점        osv.vulns = 0 → 5   1~2 → 3   3+ → 2
심각도        osv.max_severity 가 CRITICAL 이면 → 1
라이선스      npm.license 가 허용형(MIT/Apache/BSD) → 유지
              copyleft(GPL/AGPL) → −1
              불명 → −1
deprecated    npm.deprecated 또는 pypi.yanked → 1

→ 하한 1, 상한 5로 클램프
```

`osv.*`는 절단선 1번이라 [STEP 10](../../002_개발계획/STEP-10-선택.md)까지 dossier에
없다. **없으면 취약점·심각도 항목을 건너뛴다** — 0건으로 간주해 5를 주지 않는다.
"조회하지 않았다"와 "조회했더니 0건이다"는 다른 사실이고, 뒤엣것으로 대접하면
`risk`가 근거 없이 후해진다. `osv`를 붙이면 공식은 그대로 두고 사실만 늘어난다.

근거가 될 사실이 하나도 없으면 `maturity`와 같이 `unavailable`이다.

두 공식 모두 `facts` 테이블에서 SQL로 값을 꺼낸다.

```sql
SELECT value FROM facts
WHERE slug = ? AND candidate = ? AND fact_id = 'npm.last_release';
```

`rubric.py`에는 이 두 공식만 있다. 가중치 매핑·정규화 로직은 없다.

---

## `scores.source`가 하는 일

행마다 무엇으로 나온 점수인지 기록한다.

| 값 | 뜻 |
|---|---|
| `computed` | dossier 숫자로 코드가 계산 (`maturity` · `risk`) |
| `judged` | judge가 판단 (`overall`) |
| `unavailable` | 계산할 숫자가 없다 (`method` 후보 등). `score`는 `NULL` |

보고서에서 "이 후보는 성숙도를 판정할 근거가 없다"를 정직하게 표시할 수 있다.
`method` 후보가 `library` 후보보다 불리해 보이지 않게 하는 장치이기도 하다 —
점수가 낮은 게 아니라 **없는** 것이다.

---

## 출력

```sql
scores (slug, candidate, criterion, score, source, reason)
       -- criterion: maturity | risk | overall
       -- source:    computed  | judged | unavailable
       -- reason:    계산 근거 요약 또는 judge의 score_reason

picks  (slug, component, candidate, rank, rejected_reason,
        winner_reason, runner_up_note, margin)
```

`scores`에는 **탈락 후보의 `maturity`·`risk`도 들어간다.** 탈락 후보를 계산에서 빼면
"judge는 통과시켰지만 계산은 1을 줬다"를 보고서에서 보여줄 수 없고, 이중 안전망이
작동한 증거가 사라진다. `overall`만 통과 후보의 것이다.

`picks`에는 통과 후보와 탈락 후보가 모두 들어간다.
탈락은 `rank = NULL` + `rejected_reason` 채움. 보고서의 "탈락 사유 부록"이 이 행들이다.
`winner_reason` · `runner_up_note` · `margin`은 1위 행에 담는다.

---

## 실패 처리

| 상황 | 동작 |
|---|---|
| 요소의 통과 후보가 0개 | LLM을 부르지 않고 `picks`에 "전 후보 탈락" 기록. 보고서에 경고로 노출 |
| 통과 후보가 1개 | LLM을 부르지 않고 그대로 1위. 호출 낭비를 막는다 |
| dossier 숫자가 없어 계산 불가 | `score = NULL`, `source = "unavailable"` |
| `winner`가 `ranking[0]`과 불일치 | 구조 검증에서 잡고 1회 재시도 |
| `winner_reason`에 제약 인용 없음 | 경고 로그. 프로토타입에서는 통과시킨다 |
| `overall`이 `maturity`·`risk`의 평균과 같음 | 경고 로그 — 프롬프트 반례가 안 먹혔다는 신호 |
| `ranking`이 `overall` 내림차순이 아님 | 코드가 재정렬. 동점은 `maturity` → 이름 순 |
| 구조화 출력 파싱 실패 | `include_raw=True`로 원본 확보 후 1회 재시도 |

---

## 절단 시

이 단계는 절단 대상이 아니다. 요소 3개면 LLM 호출이 3회뿐이다.

잘라낸 것 중 이 단계와 관련된 것:

| 뺀 것 | 왜 |
|---|---|
| 평가 가중치 (`interview` 도출 + 가중 합산) | 배수 근거가 임의적이고 튜닝할 시간이 없다. judge가 제약조건을 직접 읽는다 |
| 기준별 LLM 점수 (`fit` · `team_fit` · `exit_cost`) | 재료가 `verify`의 `solves_reason`/`pros`/`cons`/`caveats`에 있고, 따로 매기면 judge가 평균해 `overall`을 낼 유혹이 커진다. `overall` + `score_reason` 하나로 대체 |
| `ecosystem` 기준 | npm 다운로드 추이가 필요한데 `npm_downloads` 툴을 잘라냈다 |
| `ops_cost` 기준 | 운영 비용은 정성 조사가 필요하다. 예산은 `refined_brief`로 judge에게 직접 간다 |
