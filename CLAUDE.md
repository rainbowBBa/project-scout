# project-scout — 개발 가이드

만들고 싶은 소프트웨어를 한 줄로 설명하면, 어떻게 만들어야 하는지 **근거와 함께** 답하는 CLI.
AWS Bedrock(`claude-sonnet-5`) · LangGraph · uv 워크스페이스 · sqlite3

**진행 상황은 [docs/002/README](docs/002_개발계획/README.md)의 체크리스트를 본다.**
이 파일은 상태가 아니라 **규칙과 방법**을 담는다.

---

## 문서 지도

| 무엇을 알고 싶은가 | 어디를 보는가 |
|---|---|
| 왜 만드는가 · 사용자 · 가치 | [SERVICE.md](SERVICE.md) |
| 지금 무엇을 만들 차례인가 | [docs/002](docs/002_개발계획/README.md) |
| 이 단계를 어떻게 만드나 | [docs/001/stages](docs/001_기술스택-조사-에이전트-설계/stages/README.md) |
| DB 스키마 | [docs/001/03-저장](docs/001_기술스택-조사-에이전트-설계/03-저장.md) |
| 환경변수 · `.env` | [docs/001/08-설정](docs/001_기술스택-조사-에이전트-설계/08-설정.md) |
| MCP 툴 · 프로세스 구성 | [docs/001/04-아키텍처](docs/001_기술스택-조사-에이전트-설계/04-아키텍처.md) |
| 터미널 출력 양식 | [docs/001/09-출력양식](docs/001_기술스택-조사-에이전트-설계/09-출력양식.md) |
| 무엇을 잘라냈나 · 절단선 | [docs/001/06-범위와일정](docs/001_기술스택-조사-에이전트-설계/06-범위와일정.md) |
| 설계가 왜 이렇게 됐나 | [docs/001/CHANGELOG](docs/001_기술스택-조사-에이전트-설계/CHANGELOG.md) |
| `design` 단계가 하는 일 | [docs/001/stages/1-design](docs/001_기술스택-조사-에이전트-설계/stages/1-design.md) |

문서는 한국어로 쓴다.

---

## 구조

```
interview → design → search → verify → evaluate → report
   요청      구현설계   후보     판정     점수·순위   권장설계
 구체화   +결정지점  +dossier  +grounding +설계확정    HTML
          +필요성

사용자 ─▶ scout ──────▶ AWS Bedrock
             │
             └─ stdio ─▶ scout-net-mcp ─▶ 인터넷 (유일한 출구)
                  ↑
             design · search 둘 다 여기로만 나간다
```

**답의 형태**: 후보 목록이 아니라 **"이렇게 만들면 되겠다"는 설계**다.
`design`이 설계를 세우고 → 비교가 필요한 지점만 조사·판정하고 → `evaluate`가
그 결과로 설계를 확정한다.

**단계명 = 모듈 파일명 = CLI 인자.** `scout/stages/verify.py` ↔ `scout show <slug> verify`

| 넣을 것 | 어디에 |
|---|---|
| 단계 로직 | `packages/scout/src/scout/stages/<단계>.py` |
| Pydantic 스키마 | `scout/schemas.py` (전 단계 공용) |
| LLM 프롬프트 | `scout/prompts.py` (전 단계 공용, `ChatPromptTemplate`) |
| sqlite DDL·CRUD | `scout/store.py` (ORM 없음) |
| 점수 공식 | `scout/rubric.py` |
| 인용 검증 | `scout/grounding.py` |
| 웹검색 승인 게이트 | `scout/approval.py` (`design`·`search` 공용) |
| 개발용 LLM 캐시 | `scout/llm_cache.py` (기본 off — `SCOUT_LLM_CACHE=1`) |
| 진행상황 한 줄 | `scout/progress.py` (양식은 `001/09-출력양식.md`가 정본) |
| 에이전트 기록 파싱 | `scout/agentkit.py` (`design`·`search` 공용) |
| 인터넷 호출 | `packages/scout-net-mcp/src/scout_net_mcp/providers/<소스>.py` |
| HTML 템플릿 | `scout/templates/report.html.j2` |

---

## ★ 어기면 안 되는 불변식

각 항목이 설계의 특정 결정을 지탱한다. 이유를 모르면 "불편한데 바꿀까"에서 무너진다.

### 경계

1. **`scout_net_mcp`는 `scout`를 import하지 않는다** — MCP 서버를 사내 DMZ로 떼어낼 때
   코드 수정이 0이어야 한다
2. **`scout/`는 `httpx`·`requests`·`urllib`을 import하지 않는다** — ruff `TID251`이 잡는다
3. **MCP 서버 프로세스에 `AWS_*`를 넘기지 않는다** — stdio `env` 필터로 통과 변수를 제한

### 사실과 판단의 분리

4. **`verify`의 judge는 dossier의 `fact_id`만 인용한다** — 코드가 SQL 조인으로 대조한다.
   이게 없으면 이 도구는 그냥 LLM에게 물어보는 것과 같다
5. **`maturity`·`risk`는 코드가 계산한다** — judge가 낡은 사실을 무시해도 계산이 잡는
   **이중 안전망**이다
6. **`overall`은 `maturity`·`risk`의 평균이 아니다** — judge가 판단한다
7. **`report`는 LLM을 쓰지 않는다** — `scout.db`를 jinja2로 렌더링만 한다.
   "이렇게 만들면 되겠다"는 문장은 `evaluate`가 쓴다 (`final_designs`)

### 설정

8. **AWS 변수에 `SCOUT_` 접두사를 붙이지 않는다** — boto3 기본 자격 체인이 돌아야 한다
9. **크레덴셜을 `Settings`에 담지 않는다** — boto3가 직접 읽는다.
   `doctor`는 존재 여부만 찍는다 (값은 찍지 않는다)
10. **`.env`를 커밋하지 않는다** — `.env.example`만 커밋

### 실패 처리

11. **조회 실패가 파이프라인을 죽이지 않는다** — `gaps`에 기록하고 계속.
    사실을 못 구한 것도 정보다
12. **빈 섹션을 감추지 않는다** — 보고서에 "해당 없음 + 이유"를 쓴다

### 에이전트 경계

13. **`search`의 `Fact.value`는 `ToolMessage` 원본에서 나온다** — ReAct 에이전트는
    *어떤 툴을 부를지만* 정한다. 에이전트가 요약한 문장을 사실로 저장하면 dossier가
    LLM 생성물이 되어, **grounding은 통과하는데 사실은 환각인** 상태가 된다.
    불변식 4가 지탱하던 주장이 뿌리에서 깨진다
14. **`web_search`는 사람 승인을 거치고, 거부되면 원본 툴을 호출하지 않는다** —
    승인 문구만 띄우고 요청이 나가면 이 기능은 장식이다. `test_search_approval`이
    이 배선을 검사한다. npm·PyPI·GitHub는 패키지명만 나가므로 승인 대상이 아니다.
    `design`도 같은 게이트를 쓴다 (예산만 다르다: 실행 전체 3회)
15. **`design`의 툴 결과는 `facts`에 넣지 않는다** — dossier는 `search`만 만든다.
    설계 중에 스쳐본 값을 섞으면 kind 라우팅·top-up을 거치지 않은 사실이 judge의 인용
    대상이 되어, **grounding은 통과하는데 후보마다 근거 커버리지가 달라진다**.
    불변식 4·13이 서 있는 자리가 무너진다. `test_design_no_facts`가 검사한다
16. **통과한 결정 지점의 `search_hints`는 비어 있지 않다** — 영어 기술 어휘로 채운다.
    비어도 파이프라인은 돌기 때문에(그게 `analyze` 시절의 상태였다) 조용히 원래대로
    돌아간다. 비면 `gaps`에 기록한다
17. **`needs_comparison`은 `necessity`와 다른 축이다** — "필요한가"와 "지금 비교해서
    골라야 하는가"는 다르다. 둘 다 `search`를 건너뛰지만 보고서에는 **다른 섹션**으로
    남는다 (필요 없는 것 / 이미 정해진 것)
18. **결정 지점은 `alternatives`가 2개 이상이다 — 아니면 코드가 닫힌 결정으로 내린다** —
    결정 지점은 **교체 단위**(아키텍처·저장소·프레임워크·라이브러리·배포)이고
    `decision_question`은 "무엇을 **고를** 것인가"다. "어떻게 구성할 것인가"는 선택이
    아니라 설계 판단이고, 그게 통과하면 `search`가 억지 후보를 만들어 **질문에 답하지
    않는 후보가 1위로 올라온다**. 프롬프트 반례로는 못 막아서 `design.close_undecidable`이
    코드로 내리고 이유를 채운다. 내려간 것은 `gaps`와 보고서에 남는다(불변식 12).
    `search`는 대안을 **최소 커버리지**로 받고, 안 걸린 대안을 `gaps`에 남긴다.
    `test_decision_points`가 검사한다

---

## 코드 패턴

이 프로젝트에서 반복되는 형태. 새 코드는 여기 맞춘다.

### LLM 구조화 출력

```python
from scout.llm import invoke_structured
from scout.prompts import (
    STAGE_PROMPT,
    STAGE_RETRY_HINT,
)  # prompts.py — 프롬프트 문자열은 여기, 조립 로직만 stages/에

structured_llm = llm.with_structured_output(Model, include_raw=True)
parsed, raw = invoke_structured(STAGE_PROMPT, structured_llm, prompt_input, STAGE_RETRY_HINT)
if parsed is None:  # 재시도까지 실패 — Verdict 처럼 필드 많은 스키마에서 특히 필요
    raise RuntimeError(f"... 구조화 출력 파싱 실패: {raw}")
```

프롬프트에는 **앵커(반례)를 박는다.** "판단해라"만 쓰면 judge가 후하게 준다 —
`overall`은 평균이 아니라는 반례 4개, `solves_it=false` 조건 3개처럼
**구체적으로 무엇이 그 값이어야 하는지** 쓴다.

### MCP 툴 호출 — `search`는 에이전트가 고른다

```python
from langchain.agents import create_agent   # langgraph.prebuilt.create_react_agent는 deprecated

agent = create_agent(llm, tools, system_prompt=..., checkpointer=False)  # 툴 선택은 LLM
result = await agent.ainvoke({"messages": [...]}, config={"recursion_limit": 40})
facts = facts_for_candidate(collect_tool_calls(result["messages"]), name, now)  # 값은 코드가
```

`checkpointer=False`가 필수다 — 안 주면 바깥 그래프의 `SqliteSaver`(동기 전용)를
물려받는데 이 에이전트는 `ainvoke`로 돈다.

`search` 밖에서 툴이 필요하면 코드가 직접 부른다:

```python
result = await tool.ainvoke({"name": candidate})
```

### fan-out

```python
Send("verify_candidate", {...})  # 요소별 · 후보별
Annotated[list, operator.add]  # 리듀스
Semaphore(settings.scout_llm_concurrency)  # LLM 4
Semaphore(settings.scout_mcp_concurrency)  # MCP 8 (서버 레이트리미터와 이중 방어)
```

### 저장

```python
store.upsert_facts(slug, candidate, facts)  # sqlite3 직접. ORM 없음
Model.model_validate(row) / model.model_dump()  # Pydantic ↔ dict
```

`fact_id`는 `<출처>.<항목>` 규칙 — `npm.last_release`, `gh.archived`, `web.3`.

### 실패

```python
try:
    facts = await fetch(...)
except ProviderError as e:
    store.add_gap(slug, candidate, f"{source} 조회 실패: {e}")  # 예외를 던지지 않는다
```

---

## 확장 레시피

### 새 MCP provider 추가 (가장 흔한 확장)

1. `scout_net_mcp/providers/<소스>.py` — 함수 + `Fact` 변환
2. `server.py`에 툴 등록
3. `SCOUT_EGRESS_ALLOWLIST` 기본값에 호스트 추가
4. `scout/stages/search.py`의 **kind 라우팅**에 추가 (`library`/`software`/`method`).
   `design`도 툴을 쓰지만 **사실은 저장하지 않으므로** 라우팅 대상이 아니다 (불변식 15)
5. `fact_id`를 `<출처>.<항목>` 규칙으로
6. 점수에 쓸 거면 `rubric.py` 공식 갱신
7. 문서: `001/04-아키텍처.md` 툴 표 + `001/stages/2-search.md` 라우팅 표

### 새 `fact_id` 추가 (provider가 이미 있을 때)

위의 5 · 6 · 7만. `facts` 테이블은 스키마 변경이 없다 (행이 늘 뿐).

### 새 단계 추가

`schemas.py` → `stages/<name>.py` → `graph.py`(노드+엣지) → `store.py`(테이블) →
`cli.py`(`show` 인자) → `001/stages/<n>-<name>.md` 신설 → `002/STEP-XX` 신설

**단계명은 동사 한 단어.** 6개를 유지하는 게 기본이고, 추가는 마지막 수단이다.

### 규모 조절

코드를 고치지 않는다. `--max-components` · `--max-candidates` 또는 `.env`.

---

## 흔한 함정

이 설계에서 특히 하기 쉬운 실수다. 전부 "편해 보이는데 설계를 무너뜨리는" 것들이다.

| 유혹 | 왜 안 되나 |
|---|---|
| `overall`을 `(maturity+risk)/2`로 계산 | 가중치 없는 가중 합산이다. judge가 판단해야 한다 (불변식 6) |
| `maturity`도 LLM이 매기게 하기 | 이중 안전망이 깨진다. judge 하나에만 걸린다 (불변식 5) |
| `search`의 dossier를 에이전트 응답에서 만들기 | 사실이 LLM 생성물이 된다. `ToolMessage` 원본에서 코드가 뽑는다 (불변식 13) |
| `design`이 툴로 본 값을 `facts`에 저장하기 | 라우팅·top-up을 안 거친 사실이 dossier에 섞인다 (불변식 15) |
| `search_hints`를 요소 이름으로 채우기 | `npm_search`에 한국어 추상어가 나간다. 영어 기술 어휘여야 한다 (불변식 16) |
| `needs_comparison`을 `necessity`에 합치기 | "필요 없어서"와 "이미 정해져서"가 뭉개진다 (불변식 17) |
| 결정 지점을 기능 단위로 쪼개기 | "에러 처리를 어떻게 할 것인가"는 고를 것이 없다. 교체 단위여야 한다 (불변식 18) |
| 브리프가 지정한 기술을 다시 비교하기 | 사용자가 정해준 답이 결론으로 돌아온다. 정보가 0이다 (불변식 18) |
| `combination_risks`에 `cons`를 옮겨 적기 | 사용자가 같은 문장을 두 번 읽는다. 조합해서 생긴 위험만 담는다 |
| 근거 없이 `shape`·`data_flow`를 다시 쓰기 | `changes_from_design`이 "표현을 다듬었다"로 채워져 정말 바뀐 게 안 보인다 |
| `designs`를 확정본으로 덮어쓰기 | "조사해보니 전제가 바뀌었다"가 사라진다. v1·v2 둘 다 남긴다 |
| 승인 문구만 띄우고 툴은 그냥 호출하기 | 보안 기능이 장식이 된다. 거부는 원본 툴을 부르지 않아야 한다 (불변식 14) |
| `report`에 LLM으로 요약 문장 생성 | 프롬프트 튜닝에 반나절이 사라진다. `final_designs`·`solves_reason`을 인용한다 (불변식 7) |
| `SCOUT_AWS_REGION` 같은 이름 만들기 | boto3 기본 자격 체인이 깨진다 (불변식 8) |
| 조회 실패 시 예외 던지기 | 요소 하나가 전체를 죽인다. `gaps`에 기록한다 (불변식 11) |
| 빈 섹션을 보고서에서 지우기 | 없는 걸 없다고 말하는 게 보고서의 일이다 (불변식 12) |
| 테스트를 줄이기 | 6종은 커버리지가 아니라 **설계 주장의 증거**다 |
| M0 확인 항목을 추측으로 채우기 | 모델 ID 형태 · DDG 패키지 이름 · boto3 버전은 `doctor`로 실측한다 |

---

## 용어

| 용어 | 뜻 |
|---|---|
| **설계** (`Architecture`) | `design`이 세우는 구현 설계. 구조·데이터 흐름·구축 순서 |
| **요소 · 결정 지점** (`Component`) | 설계의 구성 단위이면서 **비교해서 정해야 할 지점**. "실시간 메시지 전달", "인증" |
| **닫힌 결정** (`needs_comparison=false`) | 필요하지만 이미 정해진 것. 조사하지 않고 전제로 쓴다 |
| **후보** (`Candidate`) | 결정 지점을 구현하는 방법·소프트웨어·라이브러리. `kind`로 구분 |
| **dossier** | 후보 하나에 대해 모아둔 **사실 자료철**. judge가 인용할 수 있는 유일한 집합 |
| **사실** (`Fact`) | dossier 항목 하나. `fact_id`(`npm.last_release` 등)를 갖는다 |
| **판정** (`Verdict`) | judge가 후보에 내리는 결론. `solves_it` + 장단점 + `citations` |
| **grounding** | judge의 인용이 dossier에 실제로 있는지 코드가 대조하는 검증 |
| **권장 설계** (`FinalDesign`) | `evaluate`가 기본틀을 조사 결과로 **수정해 확정한** 설계. `Architecture`와 같은 이름의 `shape`·`data_flow`를 갖는 v2. 보고서 최상단 |

비유는 **법정**이다 — 판사(judge)가 자료철(dossier)을 읽고 판정하고, 자료철 밖은 인용할 수 없다.

---

## 명령

```bash
uv sync                           # 전체 설치 (Python 3.14 자동 조달)
uv sync --package scout-net-mcp   # MCP 서버만 (사내 DMZ 배포 리허설)
uv run ruff check --fix . && uv run ruff format .
uv run ty check                   # 정보용. 게이트 아님 — 오탐 많으면 끈다
uv run pytest                     # 6종

uv run scout                      # 기본 진입점 — 설명을 대화형으로 입력받아 전체 파이프라인을 돈다
uv run scout doctor               # AWS 자격·리전·모델·동시쿼터 확인
uv run scout run "..."            # 개발용: 설명을 인자로 직접 넘긴다. 기본 규모: 결정 지점 3개 · 후보 8~10개
uv run scout run "..." --stop-after design --auto-approve-search
uv run scout show <slug> design
```

### ★ 개발 프로파일 — 호출 40회 → 8~10회, 반복은 0회

LLM 호출이 기본값에서 한 번에 약 40회다(`search`가 절반). 개발 중에는 규모를 줄이고
캐시를 켠다 — **코드를 고치지 않는다.**

```bash
# .env
SCOUT_INTERVIEW_MAX_TURNS=2       # interview 6 → 3
SCOUT_LLM_CACHE=1                 # 2회차부터 Bedrock 호출 0

uv run scout run "..." --max-components 1 --max-candidates 2 --auto-approve-search
#   search 21 → 7 · verify 9 → 2 · evaluate 3 → 1
uv run scout run "..." --stop-after design    # 뒤 단계 0
```

캐시 키가 프롬프트 문자열이라 **프롬프트를 고치면 그 단계만 자동으로 미스**가 된다.
실행 끝에 `캐시 적중 N / 미스 M`이 찍힌다.

**판단 품질을 볼 때는 캐시를 끈다** — 같은 프롬프트+입력이면 비결정성이 사라져
judge의 편차를 못 본다 ([08-설정](docs/001_기술스택-조사-에이전트-설계/08-설정.md)).

**`--from`은 아직 값만 검증하고 실제로 앞 단계를 건너뛰지 않는다** — 재개는 전적으로
`SqliteSaver` 체크포인터가 한다. 그래서 프롬프트만 고쳐서 한 단계를 다시 돌리는 건 지금
안 된다. **새 slug로 돌리거나** `runs/<slug>/checkpoints.sqlite`를 지운다
(STEP-13 항목 4).

저장이 파일인 이유는 그대로다 — dossier 수집이 가장 비싼 단계이므로 결과가 디스크에
남아야 한다.

---

## 작업 규칙

- **설계를 바꾸면** `docs/001`의 해당 파일을 고치고 `CHANGELOG.md`에 기록한다.
  본문에는 **현재 상태만** 쓴다 — "전에는 이랬다"는 CHANGELOG로
- **STEP을 끝내면** `docs/002/README.md` 체크리스트를 갱신한다
- **시간이 부족하면** [절단선](docs/001_기술스택-조사-에이전트-설계/06-범위와일정.md)
  순서대로 버린다. `web_search`와 grounding 검출은 버리지 않는다
- **테스트 6종은 줄이지 않는다** (`test_grounding` · `test_stale_regression` ·
  `test_necessity_wiring` · `test_egress` · `test_search_approval` · `test_design_no_facts`)
- **주석은 WHY만 남긴다.** 코드가 이미 보여주는 것(WHAT)을 말로 다시 풀어 쓰지
  않는다. 불변식의 이유·워크어라운드·놀랄 만한 동작처럼 코드만 보고는 알 수 없는
  것만 짧게 적는다. 긴 설계 논증(선택지 비교, 트레이드오프)은 코드가 아니라
  `docs/001`의 해당 파일과 `CHANGELOG.md`에 쓴다 — 코드 주석에서는 그 문서를
  가리키는 한 줄로 충분하다
- **불확실한 건 단정하지 않는다.** `doctor`로 실측한 값을 `.env`에 고정하고,
  아직 모르는 건 문서에 "M0에서 확인"으로 남긴다
- **`.env` 파일을 절대 직접 읽지 않는다.** `cat`·`Read`·`grep` 등 어떤 방식으로도 열어보지
  않는다 — 크레덴셜 값을 실제로 볼 필요가 없다. 설정을 확인해야 하면 `doctor`나 테스트를
  돌려서 그 출력(존재 여부·성공/실패)으로만 판단한다
- **명시적으로 요청받지 않으면 worktree를 만들지 않는다.** 기본은 `main`에 바로 이어서
  개발한다. worktree는 사용자가 "worktree로", "격리해서"처럼 직접 말했을 때만 쓴다
