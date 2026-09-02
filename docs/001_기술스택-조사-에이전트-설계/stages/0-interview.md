# 0 · interview

← [단계 목록](README.md) · 다음: [1-analyze](1-analyze.md)

**막연한 요청을 되묻고 구체화한다.**
모듈 `scout/stages/interview.py` · 테이블 `runs` · LLM 1회

---

## 목적

"실시간 채팅 앱 만들고 싶어요" 한 줄로는 Firebase도 정답이고 Kafka도 정답이다.
**판정이 갈리는 건 기술이 아니라 제약조건이다.**

이 단계는 그 제약조건을 캐내고, 흩어진 답을 **한 덩어리 명세(`refined_brief`)**로 만든다.
뒤의 모든 단계가 이 명세를 프롬프트에 그대로 넣는다.

---

## 입력

사용자가 CLI에 넘긴 자연어 설명 한 줄.

```
uv run scout run "AI 요약 기능이 있는 팀 채팅 앱을 만들고 싶어"
```

설명 안에 이미 답이 들어 있으면 그 질문은 건너뛴다.
`"... 3인 팀, TypeScript 숙련, 월 $200, 3개월"`처럼 쓰면 되묻지 않는다.

---

## 질문 5개

| 질문 | 왜 필요한가 |
|---|---|
| 예상 사용자 규모 | 200명과 20만명은 완전히 다른 스택이다 |
| 월 인프라 예산 | 관리형이냐 자체 운영이냐를 가른다 |
| 팀 인원 / 숙련 언어 | 배울 시간이 있는지가 스택 선택을 지배한다 |
| 데드라인 | 검증된 것 vs 최신 것의 균형점을 정한다 |
| 데이터 민감도 · 규제 | 취약점·라이선스가 결정적이 되는지 |

사용자가 "모르겠다"고 하면 **기본값을 제시하고 그 가정을 기록**한다.
막연한 질문을 반복해 묻지 않는다 — 답을 모르는 건 정상이고, 가정을 명시하면 충분하다.

---

## 스키마

```python
class Interview(BaseModel):
    raw_description: str          # 원래 입력
    refined_brief: str            # ★ 구체화된 프로젝트 명세 3~5문장
    scale: str                    # "사내 200명"
    budget_monthly_usd: int | None
    team_size: int
    team_languages: list[str]     # ["TypeScript"]
    deadline_months: float
    data_sensitivity: Literal["public", "internal", "regulated"]
    must_haves: list[str]         # ★ 반드시 되어야 하는 것
    non_goals: list[str]          # ★ 이번에 안 하는 것
    assumptions: list[str]        # ★ 답하지 않아 기본값을 쓴 항목
```

---

## ★ `refined_brief` — 이 단계의 산출물

되묻기로 얻은 답을 합쳐 한 덩어리 명세로 만든다.

> 사내 200명이 쓰는 팀 채팅 앱. 실시간 메시지 전달과 AI 요약이 핵심 기능.
> 3인 TypeScript 팀이 3개월 내 출시. 월 인프라 예산 $200.
> 사내 데이터만 다루고 외부 규제는 없음. 전문검색과 외부 공개는 이번 범위 밖.

이게 `analyze` · `verify` · `evaluate` 프롬프트에 **그대로** 들어간다.
매 단계에서 제약조건을 필드별로 재조립하지 않는다 — 조립을 한 번만 한다.

`verify`의 judge가 "3인 팀 3개월"을 근거로 `caveats`를 적을 때,
`evaluate`가 "예산 $200"을 근거로 1위를 고를 때, 둘 다 이 문단을 읽는다.

---

## `must_haves` / `non_goals`

구체화의 결과가 가장 뾰족하게 드러나는 두 필드다.

```
must_haves:  ["메시지 전달 지연 1초 이내",
              "기존 사내 SSO 연동",
              "관리형 서비스 우선 — 직접 운영할 인력 없음"]

non_goals:   ["메시지 전문검색 — 나중에",
              "외부 사용자 공개",
              "모바일 네이티브 앱"]
```

### `non_goals`는 `analyze`로 직접 흐른다

사용자가 "검색은 나중에"라고 말하면 `non_goals`에 들어가고,
`analyze`가 그 요소를 `defer`로 분류하는 근거가 된다.

**사용자가 명시한 범위 밖은 조사하지 않는다.** 후보 수·토큰·시간이 함께 줄어든다.

### `must_haves`는 `verify`의 판정 기준이 된다

"관리형 서비스 우선"이 `must_haves`에 있으면, judge가 자체 운영이 필요한 후보에
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

`refined_brief` · `must_haves` · `non_goals` · `assumptions`는 모두 `interview_json` 안에 있다.

`slug`는 설명에서 만든다 (예: `2026-09-02-team-chat-ai-summary`).
같은 slug로 다시 실행하면 이어서 돈다.

---

## 실패 처리

| 상황 | 동작 |
|---|---|
| 사용자가 질문에 답하지 않음 (빈 입력) | 기본값 사용 + `assumptions`에 기록 |
| 대화형 입력이 불가능한 환경 (파이프·CI) | 전부 기본값 + `assumptions`에 "비대화형 실행" 기록 |
| `refined_brief`가 원문을 그대로 복사 | 구체화 실패. 되묻기 답이 반영됐는지 확인 — 프롬프트에 "답변 내용을 문장에 녹여라"를 명시 |
| 구조화 출력 파싱 실패 | `include_raw=True`로 원본 확보 후 1회 재시도 |

---

## 절단 시

[절단선 5번](../06-범위와일정.md). 대화형 되묻기를 없애고 고정 기본값으로 대체한다.

```python
DEFAULT_INTERVIEW = Interview(
    raw_description=user_input,
    refined_brief=user_input,     # 구체화 없이 원문 그대로
    scale="미지정 (중소 규모 가정)",
    budget_monthly_usd=None,
    team_size=3,
    team_languages=["TypeScript"],
    deadline_months=3,
    data_sensitivity="internal",
    must_haves=[],
    non_goals=[],
    assumptions=["interview 단계 생략 — 전부 기본값"],
)
```

**절단해도 "가정이 명시된다"는 성질은 유지된다** — 그게 이 단계의 핵심이다.
`refined_brief`가 원문 그대로가 되면 뒤 단계의 판단 품질이 떨어지지만 파이프라인은 돈다.
