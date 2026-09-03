# 1 · design

← [단계 목록](README.md) · 이전: [0-interview](0-interview.md) · 다음: [2-search](2-search.md)

**이 프로젝트를 어떻게 만들지 설계하고, 그 설계에서 비교가 필요한 결정 지점을 뽑는다.**
모듈 `scout/stages/design.py` · 테이블 `designs` `components` · LLM 2회 + MCP

---

## 목적

세 가지를 한다.

1. **구현 설계를 세운다** — 구조·데이터 흐름·구축 순서. 사용자가 받고 싶은 답은
   "이런 요소들이 필요합니다"가 아니라 **"이렇게 만들면 되겠습니다"**다
2. 설계를 세우는 데 필요한 만큼 **툴로 확인한다** — 후보 이름·패턴명·생태계 어휘
3. 설계에서 **비교 분석이 필요한 지점**을 뽑고, 각 지점이 정말 필요한지 판단한다

3번의 필요성 판단이 이 도구에서 가장 값어치 있는 기능일 수 있다.
**안 만들어도 되는 걸 안 만들게 하는 게 최고의 추천이다.**

### 왜 요소 나열이 아니라 설계인가

이 단계는 v20까지 `analyze`였고, 산출물이 기술 중립적인 **요소 목록**이었다
(`실시간 메시지 전달`, `인증`). 두 가지가 걸렸다.

- 추상 명사구만으로는 `search`가 후보를 잘 못 찾는다. 검색 대상(npm·PyPI·웹)은 영어
  생태계이고, `npm_search("실시간 메시지 전달")`에서는 신호가 나오지 않는다
- 최종 보고서가 "요소별로 이걸 골랐다"에서 멈춘다. 고른 것들을 **어떻게 조립하는지**가
  없으면 사용자는 여전히 설계를 직접 해야 한다

설계를 먼저 세우면 두 문제가 같은 자리에서 풀린다. 설계가 있으면 각 결정 지점에
**무엇을 정해야 하는지**(`decision_question`)와 **어떤 조건을 만족해야 하는지**
(`constraints`)가 생기고, 그게 곧 `search`의 조사 지시가 된다. 경위는
[CHANGELOG v20](../CHANGELOG.md).

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
class Architecture(BaseModel):   # 기본틀(v1). evaluate 가 조사 결과로 수정해 확정한다
    summary: str              # 이 프로젝트를 어떻게 만들 것인가 — 3~5문장
    shape: str                # 구조: 프로세스·레이어 구성
    data_flow: str            # 데이터가 어떻게 흐르는가
    build_order: list[str]    # 무엇부터 만드나
    open_questions: list[str] # 설계 단계에서 답하지 못한 것

class Component(BaseModel):
    name: str            # "실시간 메시지 전달", "메시지 저장", "인증", "배포·운영"
    kind: Literal["feature", "data", "infrastructure", "integration", "ops"]
    role_in_design: str        # 이 설계에서 이 조각이 맡는 역할
    decision_question: str     # 무엇을 정해야 하는가 — 비교의 질문
    constraints: list[str]     # 설계가 강제하는 선택 조건 — 후보 필터
    needs_comparison: bool     # false면 설계에서 이미 닫힌 결정
    no_comparison_reason: str  # needs_comparison=false 일 때의 근거
    necessity: Literal["essential", "valuable", "defer", "unnecessary"]
    necessity_reason: str
    priority: int              # ★ 1이 가장 중요. search 대상 선정에 쓴다
    approach_notes: str        # 어떻게 개발하는 게 좋은지 — 방향과 제약
    search_hints: list[str]    # ★ 영어 기술 어휘. search의 질의 씨드

class Design(BaseModel):
    architecture: Architecture
    components: list[Component]
```

### `name`은 기술 중립이어야 한다

요소 이름에 라이브러리 이름이 등장하면 그 시점부터 편향이 시작된다.

| 좋음 | 나쁨 |
|---|---|
| 실시간 메시지 전달 | WebSocket 서버 |
| 메시지 전문검색 | Elasticsearch 도입 |
| LLM 요약 호출 | LangChain 파이프라인 |

이건 `search`가 후보를 넓게 보게 하려는 장치다. **구체적인 기술 어휘는 없애는 게 아니라
`search_hints`로 옮긴다** — 이름은 중립을 유지하고, 검색 재료는 따로 준다.

### `search_hints` — 이 단계의 산출물 중 `search`에 가장 직접 작용하는 값

**영어 기술 어휘로 쓴다.** 검색 대상이 영어 생태계이기 때문이다.

```
name:         실시간 메시지 전달          ← 기술 중립 (편향 방지)
search_hints: socket.io                  ← 영어 어휘 (검색 재료)
              ws websocket library node
              server-sent events chat
              websocket reconnection room broadcast
```

**비어 있으면 안 된다.** 비면 `search` 에이전트는 `조사 힌트: (없음)`을 받은 채로
"`npm_search`를 먼저 쓴다"는 지시를 수행하게 되고, 넣을 질의가 한국어 추상 명사구밖에
남지 않는다. 통과 요소의 `search_hints`가 비면 `gaps`에 기록한다.

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
자체 실시간 인프라    unnecessary   "관리형으로 충분. 3인 팀이
                                   3개월에 직접 운영할 여력이 없다"
파일 업로드          valuable      "채팅에 필수는 아니지만 사용 빈도가 높다"
인증                essential     "사내 도구라도 신원 확인은 필요"
```

`necessity_reason`에 **제약조건을 인용**해야 한다. "200명", "3인 팀", "3개월"처럼
`interview`에서 나온 숫자가 이유에 등장해야 판단에 근거가 있는 것이다.

---

## `needs_comparison` — 필요한 것과 **정해야 할 것**은 다르다

`necessity`가 "이게 필요한가"라면 `needs_comparison`은 "**이걸 지금 비교해서 골라야
하는가**"다. 두 축은 독립이다 — 반드시 필요하지만 이미 정해진 것이 있다.

```
서버 런타임·언어   essential + needs_comparison=false
  "3인 TypeScript 팀이라고 refined_brief에 명시되어 있다. 언어 선택은 이미 닫힌
   결정이므로 후보 비교에 예산을 쓰지 않는다. 설계는 이 값을 전제로 세웠다."

배포·운영         valuable + needs_comparison=false
  "사내 표준 배포 파이프라인을 쓴다고 인터뷰에서 나왔다."
```

이 축이 없으면 두 가지가 망가진다.

- **예산이 새어나간다** — 이미 정해진 걸 조사하느라 `search`·`verify` 호출을 쓴다
- **설계가 전제를 숨긴다** — 설계는 "TypeScript"를 전제로 세웠는데 보고서에는 그 전제가
  안 보인다

`needs_comparison=false`인 요소는 **버리지 않는다.** `components`에 저장하고 보고서의
"설계에서 이미 정해진 부분"에 이유와 함께 싣는다 (불변식 12).

프롬프트에 반례를 박아야 한다 — 안 쓰면 LLM이 전부 `true`로 준다.

---

## 동작 — 2-pass (`search`와 같은 형태)

### 1. 탐색 — ReAct 에이전트

```python
agent = create_agent(llm, tools, system_prompt=DESIGN_AGENT_SYSTEM_PROMPT, checkpointer=False)
messages, truncated = await run_agent_loop(agent, task, limit)   # agentkit · astream
```

에이전트가 툴을 부르며 설계를 세운다. 무엇을 확인하는가:

- 이 구조에 쓸 수 있는 **후보 이름·패턴명이 실제로 존재하는가**
- 생태계에서 통하는 **영어 어휘가 무엇인가** — `search_hints`의 재료
- 레지스트리에 없는 **아키텍처 패턴·사례**

**어느 툴을 쓸지는 에이전트가 판단한다.** 프롬프트는 툴 5종이 무엇을 돌려주는지만
설명하고 선택을 지시하지 않는다 — 지시하면 npm만 부르는 편향이 난다
([CHANGELOG v25](../CHANGELOG.md)).

`checkpointer=False`가 필수다 — 안 주면 바깥 그래프의 `SqliteSaver`(동기 전용)를
물려받는데 이 에이전트는 `astream`으로 돈다.

#### 툴 루프 상한 — `recursion_limit` 10, 그리고 걸려도 죽지 않는다

`recursion_limit`은 **툴 호출 수가 아니라 superstep 수**다. ReAct는 한 바퀴가
model + tools 두 스텝이라 **10이면 툴 호출 4~5회**쯤이다
(`SCOUT_DESIGN_RECURSION_LIMIT`). 설계는 후보 이름·어휘만
확인하면 되므로 프로토타입에서는 그 정도로 충분하고, 루프를 오래 돌면 누적 입력이
토큰을 그대로 먹는다.

`ainvoke`가 아니라 `astream`을 쓰는 이유가 여기 있다 — **한도 초과는 예외다**
(`GraphRecursionError`). 그 예외는 상태를 담아주지 않아서 `ainvoke`로 받으면 그때까지
모은 툴 기록이 함께 날아간다. `astream`으로 마지막 상태를 들고 있으면 **부분 기록으로도
설계를 뽑을 수 있다** — 아무것도 없이 죽는 것보다 낫고, 한도 초과 사실은 `gaps`에
남는다 (불변식 11).

### 2. 추출 — 구조화 출력

```python
parsed, raw = invoke_structured(
    DESIGN_EXTRACT_PROMPT,
    llm.with_structured_output(Design, include_raw=True),
    {"transcript": build_transcript(calls, messages), "refined_brief": ..., "assumptions": ...},
    DESIGN_EXTRACT_RETRY_HINT,
)
if parsed is None:
    raise RuntimeError(f"Design 구조화 출력 파싱 실패: {raw}")
```

`build_transcript`는 툴 호출 기록을 평문으로 접는다. 원본 메시지를 그대로 다음
프롬프트에 넣으면 tool_use/tool_result 쌍이 새 toolConfig와 맞지 않아 Bedrock이
거부할 수 있다 (2-search.md와 같은 이유).

### ★ 이 단계의 툴 결과는 **사실이 아니다**

**design 에이전트의 `ToolMessage`는 `facts` 테이블에 들어가지 않는다.**

설계 어휘·후보 이름·패턴명을 잡는 데만 쓰고, judge가 인용할 dossier는 여전히
`search`만 만든다. 이유는 불변식 4·13이 서 있는 자리를 지키기 위해서다 —
judge는 dossier의 `fact_id`만 인용할 수 있고, 그 `Fact.value`는 `ToolMessage` 원본에서
**코드가** 뽑는다. 설계 단계에서 편의로 모은 사실을 dossier에 섞으면 다음이 벌어진다.

```
design이 npm_package 를 부른다 → 그 값을 facts 에 넣는다
  → verify 의 judge가 그걸 인용한다 → grounding 은 통과한다
  → 그런데 그 사실은 "설계 중에 스쳐본 것"이라 kind 라우팅·top-up·중복 제거를
    거치지 않았다 → 후보마다 사실 커버리지가 달라지고 evaluate 의 계산이
    서로 다른 근거 위에 선다
```

설계는 **어디를 조사할지 정하는 일**이고, 조사는 `search`의 일이다. 프롬프트에도
"사실 수치를 설계 문장에 쓰지 마라"를 넣는다 — 숫자는 `search`가 확인한다.

이 배선은 `tests/test_design_no_facts.py`가 검사한다.

### 웹검색 사람 승인 — 예산 3회

`web_search`는 `search`와 **같은 승인 게이트를 그대로 통과한다** (불변식 14).
거부되면 원본 툴을 부르지 않으므로 egress가 0이고, 거부 사유가 툴 결과로 에이전트에
돌아가 질의를 고쳐 재시도한다.

예산은 **이 단계 전체에서 3회**다. `search`가 요소당 5회를 쓰는 것과 다르다 —
설계는 요소별로 펼치지 않고 한 번 돌기 때문이다. 레지스트리 조회(npm·PyPI·GitHub)는
패키지명만 나가므로 승인 대상이 아니다.

게이트 인스턴스는 **`design`과 `search`가 각자 만든다.** 두 노드가 각각
`asyncio.run()`으로 이벤트 루프를 새로 열기 때문에 `SearchGate`의 `asyncio.Lock`을
공유하면 루프가 달라진다. 결과적으로 거부 3회 차단은 단계별로 센다.

### 공유 모듈

`design`과 `search`가 같은 장치를 쓰므로 stage → stage import를 만들지 않는다.

| 모듈 | 담는 것 |
|---|---|
| `scout/approval.py` | `Approval` · `Approve` · `NonInteractive` · `default_approve` · `auto_approve` · `SearchGate` · `wrap_web_search` |
| `scout/agentkit.py` | `ToolCall` · `message_text` · `parse_payload` · `collect_tool_calls` · `build_transcript` · **`run_agent_loop`** |

---

## ★ 결정 지점은 전부 도출하고, `search`에는 상위 3개만 보낸다

프로토타입 규모 제어의 핵심이다. **도출과 통과를 분리한다.**

```
design 도출      6~10개  (전부 components 테이블에 저장)
                    ↓
필터 1          necessity IN ('essential','valuable')
                    ↓
필터 2          needs_comparison = true          ← ★ 신설
                    ↓
정렬            priority 오름차순
                    ↓
search 통과      상위 3개만          ← --max-components (기본 3)
```

이렇게 하는 이유:

- **necessity 기능이 산다** — 걸러낸 요소가 `components`에 남아 보고서의
  "지금 만들지 않아도 되는 것" 섹션이 채워진다
- **이미 닫힌 결정에 예산을 쓰지 않는다** — 그러면서 보고서에서는 전제로 보인다
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

### `designs` 1행 — 설계 본문

```sql
designs (slug PK, summary, shape, data_flow, build_order_json, open_questions_json)
```

이 행이 `evaluate`의 설계 확정과 `report`의 "설계 개요" 섹션의 입력이다.

**이 행은 덮어쓰이지 않는다.** `evaluate`가 조사 결과로 수정한 확정본은
`final_designs`에 따로 들어가고, 두 버전의 대조가 보고서의 재료다 —
조사가 설계를 바꿨다는 증거이기 때문이다 ([4-evaluate](4-evaluate.md) "설계 확정").

### `components` 6~10행 — **걸러진 것까지 전부 저장한다**

```sql
components (slug, name, kind, role_in_design, decision_question, constraints_json,
            needs_comparison, no_comparison_reason, necessity, necessity_reason,
            priority, approach_notes, search_hints_json)
```

`search_hints`는 **저장한다.** 상태로만 넘기면 `store.get_components`로 돌아오는
재실행 경로에서 힌트가 사라져, 이 단계가 만든 효과가 재실행에서 소멸한다.

---

## 실패 처리

| 상황 | 동작 |
|---|---|
| 결정 지점 0개 | 조건 엣지로 조기 종료. "설명이 너무 짧다"를 보고서에 기록 |
| 통과 요소 0개 (전부 `defer` 또는 `needs_comparison=false`) | `search`를 건너뛰고 `gaps`에 기록. 설계 본문은 보고서에 남는다 |
| 통과 요소의 `search_hints`가 비어 있음 | `gaps`에 기록하고 계속 — 조사는 돌지만 얕아진다는 신호 |
| 전부 `essential` | 그대로 진행하되 경고 출력. 성공 기준 7번 미달로 표시 |
| 전부 `needs_comparison=true` | 경고. 반례가 안 먹힌 신호다 |
| 툴 조회 실패 | `gaps`에 기록하고 설계를 계속 세운다 (불변식 11) |
| 웹검색 거부·비대화형 | 레지스트리와 LLM 지식만으로 설계한다. 거부 사유를 `gaps`에 남긴다 |
| 구조화 출력 파싱 실패 | `include_raw=True`로 원본 확보 후 1회 재시도, 그래도 실패면 `RuntimeError` |

---

## 절단 시

이 단계는 **절단 대상이 아니다.** `necessity`가 후보 수를 줄여 뒷 단계를 빠르게 하므로,
오히려 시간이 부족할 때 더 필요하다.

시간이 부족하면 **툴 사용만** 잘라낸다 — 에이전트 없이 LLM 1회로 `Design`을 뽑는다.
`search_hints`의 품질이 떨어지지만 구조는 그대로 서고, `search`는 계속 돈다.
`Architecture`와 `needs_comparison`은 버리지 않는다 — 이게 없으면 `evaluate`의
설계 확정과 보고서의 "권장 설계"가 재료를 잃는다.
