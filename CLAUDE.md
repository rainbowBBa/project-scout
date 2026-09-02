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
| 무엇을 잘라냈나 · 절단선 | [docs/001/06-범위와일정](docs/001_기술스택-조사-에이전트-설계/06-범위와일정.md) |
| 설계가 왜 이렇게 됐나 | [docs/001/CHANGELOG](docs/001_기술스택-조사-에이전트-설계/CHANGELOG.md) |

문서는 한국어로 쓴다.

---

## 구조

```
interview → analyze → search → verify → evaluate → report
   요청       요소       후보      판정      점수      HTML
 구체화    +필요성   +dossier   +grounding  +순위

사용자 ─▶ scout ──────▶ AWS Bedrock
             │
             └─ stdio ─▶ scout-net-mcp ─▶ 인터넷 (유일한 출구)
```

**단계명 = 모듈 파일명 = CLI 인자.** `scout/stages/verify.py` ↔ `scout show <slug> verify`

| 넣을 것 | 어디에 |
|---|---|
| 단계 로직 | `packages/scout/src/scout/stages/<단계>.py` |
| Pydantic 스키마 | `scout/schemas.py` (전 단계 공용) |
| LLM 프롬프트 | `scout/prompts.py` (전 단계 공용, `ChatPromptTemplate`) |
| sqlite DDL·CRUD | `scout/store.py` (ORM 없음) |
| 점수 공식 | `scout/rubric.py` |
| 인용 검증 | `scout/grounding.py` |
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
7. **`report`는 LLM을 쓰지 않는다** — `scout.db`를 jinja2로 렌더링만 한다

### 설정

8. **AWS 변수에 `SCOUT_` 접두사를 붙이지 않는다** — boto3 기본 자격 체인이 돌아야 한다
9. **크레덴셜을 `Settings`에 담지 않는다** — boto3가 직접 읽는다.
   `doctor`는 존재 여부만 찍는다 (값은 찍지 않는다)
10. **`.env`를 커밋하지 않는다** — `.env.example`만 커밋

### 실패 처리

11. **조회 실패가 파이프라인을 죽이지 않는다** — `gaps`에 기록하고 계속.
    사실을 못 구한 것도 정보다
12. **빈 섹션을 감추지 않는다** — 보고서에 "해당 없음 + 이유"를 쓴다

---

## 코드 패턴

이 프로젝트에서 반복되는 형태. 새 코드는 여기 맞춘다.

### LLM 구조화 출력

```python
from scout.prompts import STAGE_PROMPT   # prompts.py — 프롬프트 문자열은 여기, 조립 로직만 stages/에

structured_llm = llm.with_structured_output(Model, include_raw=True)
chain = STAGE_PROMPT | structured_llm    # prompt | llm — 스키마는 API에 tool로 전달, 프롬프트엔 안 적는다
result = chain.invoke(prompt_input)
# result["parsed"] 가 None이면 raw 를 잡아 1회 재시도. Verdict 처럼 필드 많은 스키마에서 특히 필요
```

프롬프트에는 **앵커(반례)를 박는다.** "판단해라"만 쓰면 judge가 후하게 준다 —
`overall`은 평균이 아니라는 반례 4개, `solves_it=false` 조건 3개처럼
**구체적으로 무엇이 그 값이어야 하는지** 쓴다.

### MCP 툴 호출 — 코드가 부른다

```python
result = await tool.ainvoke({"name": candidate})   # LLM이 툴을 고르지 않는다
```

`search` 2턴만 MCP를 쓰고, LLM은 질의를 만들고(1턴) 결과를 정리(3턴)한다.
`langchain-mcp-adapters`가 `BaseTool`로 로드하므로 나중에 에이전트로 바꿀 여지는 남는다.

### fan-out

```python
Send("verify_candidate", {...})                    # 요소별 · 후보별
Annotated[list, operator.add]                       # 리듀스
Semaphore(settings.scout_llm_concurrency)           # LLM 4
Semaphore(settings.scout_mcp_concurrency)           # MCP 8 (서버 레이트리미터와 이중 방어)
```

### 저장

```python
store.upsert_facts(slug, candidate, facts)          # sqlite3 직접. ORM 없음
Model.model_validate(row) / model.model_dump()      # Pydantic ↔ dict
```

`fact_id`는 `<출처>.<항목>` 규칙 — `npm.last_release`, `gh.archived`, `web.3`.

### 실패

```python
try:
    facts = await fetch(...)
except ProviderError as e:
    store.add_gap(slug, candidate, f"{source} 조회 실패: {e}")   # 예외를 던지지 않는다
```

---

## 확장 레시피

### 새 MCP provider 추가 (가장 흔한 확장)

1. `scout_net_mcp/providers/<소스>.py` — 함수 + `Fact` 변환
2. `server.py`에 툴 등록
3. `SCOUT_EGRESS_ALLOWLIST` 기본값에 호스트 추가
4. `scout/stages/search.py`의 **kind 라우팅**에 추가 (`library`/`software`/`method`)
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
| `search`를 ReAct 에이전트로 바꾸기 | DDG 품질이 나빠 Sonnet이 헤맨다. 3턴 파이프라인을 유지한다 |
| `report`에 LLM으로 요약 문장 생성 | 프롬프트 튜닝에 반나절이 사라진다. `solves_reason`을 인용한다 (불변식 7) |
| `SCOUT_AWS_REGION` 같은 이름 만들기 | boto3 기본 자격 체인이 깨진다 (불변식 8) |
| 조회 실패 시 예외 던지기 | 요소 하나가 전체를 죽인다. `gaps`에 기록한다 (불변식 11) |
| 빈 섹션을 보고서에서 지우기 | 없는 걸 없다고 말하는 게 보고서의 일이다 (불변식 12) |
| 테스트를 줄이기 | 4종은 커버리지가 아니라 **설계 주장의 증거**다 |
| M0 확인 항목을 추측으로 채우기 | 모델 ID 형태 · DDG 패키지 이름 · boto3 버전은 `doctor`로 실측한다 |

---

## 용어

| 용어 | 뜻 |
|---|---|
| **요소** (`Component`) | 개발에 필요한 구성 단위. "실시간 메시지 전달", "인증" |
| **후보** (`Candidate`) | 요소를 구현하는 방법·소프트웨어·라이브러리. `kind`로 구분 |
| **dossier** | 후보 하나에 대해 모아둔 **사실 자료철**. judge가 인용할 수 있는 유일한 집합 |
| **사실** (`Fact`) | dossier 항목 하나. `fact_id`(`npm.last_release` 등)를 갖는다 |
| **판정** (`Verdict`) | judge가 후보에 내리는 결론. `solves_it` + 장단점 + `citations` |
| **grounding** | judge의 인용이 dossier에 실제로 있는지 코드가 대조하는 검증 |

비유는 **법정**이다 — 판사(judge)가 자료철(dossier)을 읽고 판정하고, 자료철 밖은 인용할 수 없다.

---

## 명령

```bash
uv sync                           # 전체 설치 (Python 3.12 자동 조달)
uv sync --package scout-net-mcp   # MCP 서버만 (사내 DMZ 배포 리허설)
uv run ruff check --fix . && uv run ruff format .
uv run ty check                   # 정보용. 게이트 아님 — 오탐 많으면 끈다
uv run pytest                     # 4종

uv run scout                      # 기본 진입점 — 설명을 대화형으로 입력받아 전체 파이프라인을 돈다
uv run scout doctor               # AWS 자격·리전·모델·동시쿼터 확인
uv run scout run "..."            # 개발용: 설명을 인자로 직접 넘긴다. 기본 규모: 요소 3개 · 후보 8~10개
uv run scout run "..." --from verify --max-components 8
uv run scout show <slug> verify
```

`--from`이 가장 자주 쓰인다 — 프롬프트를 고칠 때 앞 단계를 다시 돌리지 않는다.
그래서 저장이 인메모리가 아니라 파일이다.

---

## 작업 규칙

- **설계를 바꾸면** `docs/001`의 해당 파일을 고치고 `CHANGELOG.md`에 기록한다.
  본문에는 **현재 상태만** 쓴다 — "전에는 이랬다"는 CHANGELOG로
- **STEP을 끝내면** `docs/002/README.md` 체크리스트를 갱신한다
- **시간이 부족하면** [절단선](docs/001_기술스택-조사-에이전트-설계/06-범위와일정.md)
  순서대로 버린다. `web_search`와 grounding 검출은 버리지 않는다
- **테스트 4종은 줄이지 않는다**
  (`test_grounding` · `test_stale_regression` · `test_necessity_wiring` · `test_egress`)
- **불확실한 건 단정하지 않는다.** `doctor`로 실측한 값을 `.env`에 고정하고,
  아직 모르는 건 문서에 "M0에서 확인"으로 남긴다
- **`.env` 파일을 절대 직접 읽지 않는다.** `cat`·`Read`·`grep` 등 어떤 방식으로도 열어보지
  않는다 — 크레덴셜 값을 실제로 볼 필요가 없다. 설정을 확인해야 하면 `doctor`나 테스트를
  돌려서 그 출력(존재 여부·성공/실패)으로만 판단한다
- **명시적으로 요청받지 않으면 worktree를 만들지 않는다.** 기본은 `main`에 바로 이어서
  개발한다. worktree는 사용자가 "worktree로", "격리해서"처럼 직접 말했을 때만 쓴다
