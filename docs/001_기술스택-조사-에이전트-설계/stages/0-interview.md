# 0 · interview

← [단계 목록](README.md) · 다음: [1-design](1-design.md)

**막연한 요청을 되묻고 구체화한다.**
모듈 `scout/stages/interview.py` · 테이블 `runs` · LLM 다중 턴 (대화 1턴당 1회 호출)

---

## 목적

"실시간 채팅 앱 만들고 싶어요" 한 줄로는 Firebase도 정답이고 Kafka도 정답이다.
**판정이 갈리는 건 기술이 아니라 제약조건이다.**

이 단계는 그 제약조건을 캐내고, 대화 전체를 **한 덩어리 명세(`refined_brief`)**로 만든다.
뒤의 모든 단계가 이 명세를 프롬프트에 그대로 넣는다.

---

## 입력

사용자가 CLI에 넘긴 자연어 설명 한 줄.

```
uv run scout run "AI 요약 기능이 있는 팀 채팅 앱을 만들고 싶어"
```

---

## ★ 진짜 대화 — 질문 개수·내용은 LLM이 판단한다

코드는 고정된 질문 목록을 갖지 않는다. 매 턴, LLM이 지금까지의 대화(원래 설명 + 오간
질문·답변)를 보고 **둘 중 하나를 결정**한다.

- 정보가 더 필요하다 → 질문 하나를 만든다 (한 번에 하나만)
- 판단하기 충분하다 → 대화를 끝낸다

```
사용자  "AI 요약 기능이 있는 팀 채팅 앱을 만들고 싶어"
LLM    "예상 사용자 규모가 어느 정도인가요?"
사용자  "사내 200명"
LLM    "예산은 어느 정도로 생각하세요?"
사용자  "$200"
LLM    (충분하다고 판단) → 대화 종료 → refined_brief 합성
```

**설명 안에 이미 답이 있으면 그 질문은 만들지 않는다.**
`"... 3인 팀, TypeScript 숙련, 월 $200, 3개월"`처럼 쓰면 그만큼 되묻지 않는다 — 고정
질문표 방식에서는 구현하지 않았던 부분이다(이전 방식은 5개를 무조건 다 물었다).

사용자가 "모르겠다"고 하거나 빈 입력으로 넘기면 **LLM이 알아서 합리적으로 가정하고
그 가정을 기록**한다. 같은 종류의 질문을 반복하지 않는다.

### 왜 이런 정보를 확인하는가 (LLM에게 주는 가이드, 질문표가 아니다)

| 확인 대상 | 왜 필요한가 |
|---|---|
| 예상 사용자 규모 | 200명과 20만명은 완전히 다른 스택이다 |
| 월 인프라 예산 | 관리형이냐 자체 운영이냐를 가른다 |
| 팀 인원 / 숙련 언어 | 배울 시간이 있는지가 스택 선택을 지배한다 |
| 데드라인 | 검증된 것 vs 최신 것의 균형점을 정한다 |
| 데이터 민감도 · 규제 | 취약점·라이선스가 결정적이 되는지 |
| 핵심 기능 / 범위 제외 | `design`이 결정 지점을 거를 때 가장 강한 신호가 된다 |

---

## 오케스트레이션 — `stages/interview.py` 안의 LangGraph 서브그래프

대화 루프는 파이썬 for-loop가 아니라 **작은 `StateGraph`**로 짠다. 순환(cycle)은
조건 엣지가 뒤 노드에서 앞 노드로 되돌아가는 것으로 표현한다 — ReAct 루프와 같은 모양.
외부 파이프라인(`graph.py`)에서 보이는 `interview` 노드는 하나 그대로다. 그 노드가
내부적으로 이 서브그래프를 돈다.

```
        START
          │
          ▼
   ┌─ ask_question ──┐   done / 질문 없음 / 턴 한도 도달 → synthesize
   │        │         │
   │  (질문 있음)      │
   │        ▼         │
   │  get_answer      │   비대화형 입력(EOF) → synthesize
   │        │         │
   │   (계속) └────────┘ (다시 ask_question으로)
   │
   ▼
synthesize → END
```

- `ask_question` — 대화 이력을 보고 다음 질문을 만들거나(`done=false`) 끝낸다(`done=true`).
  턴 상한(`Settings.scout_interview_max_turns`, 기본 5)에 도달하면 LLM 판단 없이 강제로
  끝낸다.
- `get_answer` — CLI로 질문을 보여주고 답을 받는다. 파이프·CI처럼 입력이 즉시 EOF인
  환경에서는 바로 종료로 라우팅한다.
- `synthesize` — 대화 전체를 근거로 `Interview`(`refined_brief` + `assumptions`)를
  구조화 출력으로 만든다. 이 호출만 결과가 저장된다 — `ask_question`이 만든 질문 자체는
  버려진다.

---

## 스키마

```python
class Interview(BaseModel):
    raw_description: str    # 원래 입력
    refined_brief: str       # ★ 이 단계의 유일한 산출물 — 대화 전체를 반영한 자유 서술
    assumptions: list[str]   # ★ 답하지 않아 LLM이 추정한 항목
```

`scale`·`budget_monthly_usd`·`team_size`·`team_languages`·`deadline_months`·
`data_sensitivity`·`must_haves`·`non_goals` 같은 슬롯 필드는 없다 — 대화에서 나온 그
내용은 전부 `refined_brief` 프로즈 안에 자연어로 들어간다. 뒤 단계가 필요한 값은
`refined_brief`를 읽고 직접 판단한다.

---

## ★ `refined_brief` — 정보가 여기 다 모인다

되묻기로 얻은 답을 합쳐 한 덩어리 명세로 만든다. **정보 밀도가 핵심이다** — 대화에서
나온 규모·예산·팀·데드라인·데이터 민감도·핵심 기능·범위 제외를 하나라도 대화에
나왔다면 빠뜨리지 않고 문장으로 담는다.

> 사내 200명이 쓰는 팀 채팅 앱. 실시간 메시지 전달과 AI 요약이 핵심 기능.
> 3인 TypeScript 팀이 3개월 내 출시. 월 인프라 예산 $200.
> 사내 데이터만 다루고 외부 규제는 없음. 전문검색과 외부 공개는 이번 범위 밖.

이게 `design` · `verify` · `evaluate` 프롬프트에 **그대로** 들어간다.
매 단계에서 제약조건을 필드별로 재조립하지 않는다 — 조립을 한 번만 한다.

`verify`의 judge가 "3인 팀 3개월"을 근거로 `caveats`를 적을 때,
`evaluate`가 "예산 $200"을 근거로 1위를 고를 때, 둘 다 이 문단을 읽는다.

### 범위 제외는 `design`으로 직접 흐른다

사용자가 "검색은 나중에"라고 말하면 그 문장이 `refined_brief`에 그대로 들어가고,
`design`이 그 요소를 `defer`로 분류하는 근거가 된다.

**사용자가 명시한 범위 밖은 조사하지 않는다.** 후보 수·토큰·시간이 함께 줄어든다.

### 핵심 기능은 `verify`의 판정 기준이 된다

"관리형 서비스 우선"이 `refined_brief`에 있으면, judge가 자체 운영이 필요한 후보에
`caveats`를 달거나 `solves_it=false`를 낼 근거가 생긴다.

---

## `assumptions`

반드시 채운다. 보고서 첫 페이지의 "명시된 가정" 섹션이 이 필드다.
사용자가 나중에 "왜 이런 결론이 나왔지"라고 물을 때 답이 되는 곳이다.

```
assumptions: ["월 예산 미지정 — $200 가정",
              "데이터 민감도 미지정 — 사내 데이터로 가정"]
```

---

## 가중치는 만들지 않는다

이전 설계는 이 단계에서 5기준 평가 가중치를 도출했다. 프로토타입에서 뺐고,
**제약조건을 `refined_brief`로 judge에게 그대로 준다.** 순위 판단은 `evaluate`의 LLM이
이 문단을 읽고 직접 내린다 — 이유는 [4-evaluate](4-evaluate.md)에 있다.

---

## 출력

`runs` 테이블 한 행.

```sql
runs (slug, description, created_at, interview_json)
```

`refined_brief` · `assumptions`는 `interview_json` 안에 있다.

`slug`는 설명에서 만든다 (예: `2026-09-02-team-chat-ai-summary`).
같은 slug로 다시 실행하면 이어서 돈다.

---

## 실패 처리

| 상황 | 동작 |
|---|---|
| 사용자가 질문에 답하지 않음 (빈 입력) | LLM이 알아서 가정 + `assumptions`에 기록 |
| 대화형 입력이 불가능한 환경 (파이프·CI) | 대화 즉시 종료 + `assumptions`에 "비대화형 실행" 기록 |
| 턴 상한(`scout_interview_max_turns`) 도달 | LLM 판단 없이 강제 종료 + `assumptions`에 기록 |
| `refined_brief`가 원문을 그대로 복사 | 구체화 실패. 프롬프트에 "대화 내용을 문장에 녹여라"를 명시 |
| 질문 생성(`ask_question`) 구조화 출력 파싱 실패 | 1회 재시도. 그래도 실패하면 대화를 그냥 끝낸다 — 질문 하나 못 만드는 게 파이프라인을 막으면 안 된다 |
| 최종 합성(`synthesize`) 구조화 출력 파싱 실패 | `include_raw=True`로 원본 확보 후 1회 재시도 |

---

## 절단 시

[절단선 5번](../06-범위와일정.md). 대화형 되묻기를 없애고 고정 기본값으로 대체한다.

```python
DEFAULT_INTERVIEW = Interview(
    raw_description=user_input,
    refined_brief=user_input,     # 구체화 없이 원문 그대로
    assumptions=["interview 단계 생략 — 대화 없이 원문 그대로 사용"],
)
```

**절단해도 "가정이 명시된다"는 성질은 유지된다** — 그게 이 단계의 핵심이다.
`refined_brief`가 원문 그대로가 되면 뒤 단계의 판단 품질이 떨어지지만 파이프라인은 돈다.
