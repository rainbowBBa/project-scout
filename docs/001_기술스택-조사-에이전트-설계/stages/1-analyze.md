# 1 · analyze

← [단계 목록](README.md) · 이전: [0-interview](0-interview.md) · 다음: [2-search](2-search.md)

**개발에 필요한 요소를 도출하고, 각각 정말 필요한지 판단한다.**
모듈 `scout/stages/analyze.py` · 테이블 `components` · LLM 1회

---

## 목적

두 가지를 한다.

1. 이 프로젝트를 개발하는 데 필요한 **요소 전반**을 도출한다 — 기능뿐 아니라 데이터 저장,
   인프라, 외부 연동, 배포·운영까지
2. 각 요소가 **정말 필요한지** 판단한다

2번이 이 도구에서 가장 값어치 있는 기능일 수 있다.
**안 만들어도 되는 걸 안 만들게 하는 게 최고의 추천이다.**

---

## 입력

`runs` 테이블의 `interview_json` — `Interview.refined_brief` 전체 (0-interview.md 참고,
`Interview`는 `raw_description`·`refined_brief`·`assumptions` 세 필드뿐이다. 예산·팀·
데드라인·데이터 민감도·핵심 기능·범위 제외가 전부 이 프로즈 안에 자연어로 담겨 있다).

범위 제외는 별도 필드가 아니라 `refined_brief` 문장으로 흘러온다: 사용자가 "검색은
나중에"라고 말했으면 그 문장이 `refined_brief`에 들어가 있고, 그게 그 요소를 `defer`로
분류하는 근거가 된다. 사용자가 명시한 범위 밖은 조사하지 않는다.

---

## 스키마

```python
class Component(BaseModel):
    name: str            # "실시간 메시지 전달", "메시지 저장", "인증", "배포·운영"
    kind: Literal["feature", "data", "infrastructure", "integration", "ops"]
    why: str             # 왜 이 프로젝트에 필요한가
    necessity: Literal["essential", "valuable", "defer", "unnecessary"]
    necessity_reason: str
    priority: int        # ★ 1이 가장 중요. search 대상 선정에 쓴다
    approach_notes: str  # 어떻게 개발하는 게 좋은지 — 방향과 제약
    search_hints: list[str]   # search 단계에 넘기는 조사 방향

class Analysis(BaseModel):
    components: list[Component]
```

### `name`은 기술 중립이어야 한다

요소 이름에 라이브러리 이름이 등장하면 그 시점부터 편향이 시작된다.

| 좋음 | 나쁨 |
|---|---|
| 실시간 메시지 전달 | WebSocket 서버 |
| 메시지 전문검색 | Elasticsearch 도입 |
| LLM 요약 호출 | LangChain 파이프라인 |

`approach_notes`에는 방향을 써도 된다 — 거기는 판단을 담는 자리다.

### `kind`는 요소를 빠뜨리지 않게 하는 체크리스트

LLM은 눈에 보이는 기능만 나열하고 배포·운영·인증을 잊는 경향이 있다.
`kind` 5종을 스키마에 박아두면 프롬프트에서 "각 kind마다 최소 하나 검토하라"고 요구할 수 있다.

---

## `necessity` — 4단계

| 값 | 뜻 | `search`에 들어가는가 |
|---|---|---|
| `essential` | 없으면 제품이 아니다 | O |
| `valuable` | 있으면 낫다. 초기 범위에 넣을 만하다 | O |
| `defer` | 나중에. 지금은 더 단순한 방법으로 충분 | **X** |
| `unnecessary` | 이 프로젝트엔 필요 없다 | **X** |

### 판단 예시

```
메시지 전문검색      defer         "200명 규모면 LIKE 쿼리로 충분.
                                   전문검색 엔진은 운영 부담이 이득을 넘는다"
자체 실시간 인프라    unnecessary   "관리형 서비스로 충분. 3인 팀이
                                   3개월에 직접 운영할 여력이 없다"
파일 업로드          valuable      "채팅에 필수는 아니지만 사용 빈도가 높다"
인증                essential     "사내 도구라도 신원 확인은 필요"
```

`necessity_reason`에 **제약조건을 인용**해야 한다. "200명", "3인 팀", "3개월"처럼
`interview`에서 나온 숫자가 이유에 등장해야 판단에 근거가 있는 것이다.

### 이 필드가 만드는 효과

- **후보 수·토큰·시간이 함께 줄어든다.** 요소 10개 중 3개가 걸러지면 `search`와 `verify`
  비용이 30% 줄어든다
- **보고서에 "지금 만들지 않아도 되는 것" 섹션이 생긴다** — 사용자가 가장 놀라는 부분
- **성공 기준이 된다** ([07-검증](../07-검증.md) 7번): `unnecessary`/`defer`가 0개면
  이 기능은 장식이다
- **`test_necessity_wiring.py`가 배선을 검증한다** — 걸러놓고 `search`가 그냥 다 조사하면
  기능이 아무 효과가 없다. 그 경우를 자동으로 잡는다

---

## 동작

LLM 1회, `.with_structured_output(Analysis, include_raw=True)`.

프롬프트에 넣는 것:

- `interview.refined_brief` 전체(제약조건이 전부 자연어로 녹아있다) + `assumptions`
- **도메인 힌트 문자열** — 웹/SaaS와 AI 앱에서 흔히 빠뜨리는 요소 목록
  (인증, 마이그레이션, 관측, 비용 모니터링, 레이트리밋, LLM 응답 캐싱 등).
  `domains/` 모듈을 잘라낸 대신 프롬프트 문자열로 넣는다
- `kind` 5종 각각 최소 하나 검토 요구
- `necessity_reason`에 제약조건 숫자를 인용하라는 요구

요소 6~10개가 나오는 게 정상이다. 20개가 나오면 너무 잘게 쪼갠 것이고,
3개면 너무 뭉갠 것이다.

---

## ★ 요소는 전부 도출하고, `search`에는 상위 3개만 보낸다

프로토타입 규모 제어의 핵심이다. **도출과 통과를 분리한다.**

```
analyze 도출     6~10개  (전부 components 테이블에 저장)
                    ↓
필터            necessity IN ('essential','valuable')
                    ↓
정렬            priority 오름차순
                    ↓
search 통과      상위 3개만          ← --max-components (기본 3)
```

이렇게 하는 이유:

- **necessity 기능이 산다** — 걸러낸 요소가 `components`에 남아 보고서의
  "지금 만들지 않아도 되는 것" 섹션이 채워진다
- **통과하지 못한 essential 요소도 남는다** — 보고서에 "이번 실행에서 다루지 않음"으로
  표시하고, `--max-components 8`로 다시 돌리면 된다. 조용히 사라지지 않는다
- **규모가 CLI로 조절된다** — 프로토타입은 3개, 실전은 8개

```
uv run scout run "..." --max-components 3   # 기본. 후보 8~10개, judge 8~10회
uv run scout run "..." --max-components 8   # 풀 규모. 후보 20~25개
```

`priority`를 LLM이 매기게 하는 이유는 "무엇이 이 프로젝트의 심장인지"가 도메인 판단이기
때문이다. 채팅 앱이면 실시간 전달이 1순위고, 문서 도구면 저장·검색이 1순위다.

---

## 출력

`components` 테이블 6~10행 — **걸러진 것까지 전부 저장한다.**

```sql
components (slug, name, kind, why, necessity, necessity_reason, priority, approach_notes)
```

`search_hints`는 다음 단계에 상태로 넘긴다. 테이블에는 저장하지 않는다 —
`search`가 소비하고 끝나는 일회성 값이다.

---

## 실패 처리

| 상황 | 동작 |
|---|---|
| 요소 0개 | 조건 엣지로 조기 종료. "설명이 너무 짧다"를 보고서에 기록 |
| 전부 `essential` | 그대로 진행하되 경고 출력. 성공 기준 7번 미달로 표시 |
| `necessity_reason`이 비어 있음 | 스키마가 막는다(`str` 필수). 파싱 실패 시 1회 재시도 |
| 구조화 출력 파싱 실패 | `include_raw=True`로 원본 확보 후 1회 재시도 |

---

## 절단 시

이 단계는 **절단 대상이 아니다.** `necessity`가 후보 수를 줄여 뒷 단계를 빠르게 하므로,
오히려 시간이 부족할 때 더 필요하다.

잘라낸 `design` 단계(아키텍처 후보 2~3안)가 원래 이 뒤에 올 자리였다.
지금은 `approach_notes`가 그 역할을 얕게 대신한다 — 나중에 되살릴 후보다.
