# 변경 이력

← [문서 목록](README.md)

본문 파일들은 **현재 상태만** 서술한다. "전에는 이랬다"는 전부 여기 모았다.

---

## v18 (2026-09-03) — `verify`: 강등 규칙과 판정 정체성을 코드로 못박음

STEP-06을 구현하면서 `3-verify.md`의 "실패 처리"를 두 곳 정밀화했다. 설계의 방향을
바꾼 게 아니라, 구현하면서 드러난 빈틈을 메운 것이다.

### 1. 위반 인용을 DB에 남기지 않는다

v17까지 "2차 위반 → `confidence: low` 강등 + 카운트 기록"까지만 정해져 있었다.
그런데 **지어낸 `fact_id`가 `citations` 테이블에 그대로 남는다.** 그러면 `evaluate`와
`report`가 존재하지 않는 사실을 조인하려 들고, 불변식 4("judge는 dossier의 `fact_id`만
인용한다")가 데이터 층위에서 깨진 채로 남는다.

위반 인용은 `citations`에서 걷어내고 `unsupported_claims`로 옮긴다. 지우기만 하면
judge가 무엇을 지어냈는지가 사라지므로, **DB에는 dossier 안의 인용만 남기되 지어낸
id는 기록으로 남긴다.** 강등을 두 번 저장하는 경로가 생겨 `grounding_violations`
카운트가 0으로 덮이는 버그도 여기서 나왔다 — 인용을 전부 걷어내면 "인용 0개" 규칙에
연달아 걸린다.

### 2. 후보명·요소명은 judge가 아니라 코드가 확정한다

`Verdict`에 `candidate`·`component` 필드가 있어 judge가 채운다. judge가 이름을 조금만
바꿔 써도(`socket.io` → `Socket.IO`) `verdicts` 행이 `candidates`·`facts`와 조인되지
않고, **그러면 grounding 대조 자체가 조용히 무력해진다** — 위반이 0건으로 나온다.
파싱 직후 코드가 두 필드를 덮어쓴다.

### 판정 LLM 구성 — `search`와 다른 이유

`search`만 에이전트(`create_agent`)이고 `verify`는 툴 없는 단발 구조화 출력이다.
dossier는 이미 DB에 있으니 판정에 툴이 필요 없다. 후보당 1회(pointwise), 정상 경로는
그게 전부고 파싱 실패·grounding 위반에만 각 1회가 붙는다.

`Send` fan-out을 쓰지 않은 이유는 v17과 같다 — `cli.py`의 스트림 루프가 서브노드
이름에서 죽는다. `verify` 노드 하나가 내부에서 `asyncio.gather`로 펼치고,
동시성은 `Semaphore(scout_llm_concurrency)` = 4다 (MCP의 8이 아니다).

LLM 호출만 `asyncio.to_thread`로 뺀다. `invoke_structured`가 동기 `.invoke()`라
그냥 부르면 이벤트 루프를 막아 후보 10개가 사실상 순차 실행된다. 반대로 `store` 접근은
이벤트 루프 스레드에 남겨둔다 — 병렬 판정 중에도 sqlite 쓰기가 저절로 직렬화된다.

---

## v17 (2026-09-03) — `search`: 3턴 파이프라인 → ReAct 에이전트 + 웹검색 사람 승인

STEP-05를 구현하면서 설계 두 곳을 뒤집었다.

### 1. ReAct 에이전트로 바꿨다 — 막던 이유가 이미 사라져 있었다

v14까지 `2-search.md`는 "동작 — 3턴 파이프라인(에이전트 아님)"이었고
`STEP-05-search.md`는 "ReAct 에이전트로 바꾸려는 충동을 참는다"까지 써놨다.
근거는 하나였다 — *"DuckDuckGo 스니펫 품질이 나쁘고 모델이 Sonnet이라, 에이전트에
검색을 맡기면 헤맨다."*

**그 전제는 v15에서 이미 무너져 있었다.** v15가 backend를 duckduckgo → google로 바꾼
이유가 바로 "duckduckgo는 결과 0건인 시나리오가 있었고 신호가 약했다"는 실측이었다.
품질이 ReAct를 막던 유일한 이유였는데, 그 품질 문제를 해결한 뒤에도 결론만 남아 있었다.
두 문서 다 탈출구는 미리 적어뒀었다 — *"나중에 `create_react_agent`로 바꿀 여지는
남는다."*

실측 결과 에이전트는 헤매지 않았다. 오히려 **한 요소에 웹검색을 15번** 하는 게
문제여서 요소당 5회 예산으로 막았다.

**사실 추출은 코드가 한다.** 에이전트는 어떤 툴을 부를지만 정하고, `Fact.value`는
`ToolMessage` 원본 payload에서 코드가 파싱한다. 사실을 후보에 연결하는 것도 툴 호출
인자와 후보명을 대조하는 코드다. 이 경계가 없으면 judge가 인용하는 dossier 자체가
LLM 생성물이 되어 **grounding은 통과하는데 사실은 환각인** 상태가 된다 —
불변식 4가 지탱하던 주장이 뿌리에서 깨진다. `CLAUDE.md`에 불변식 13으로 박았다.

`Send` fan-out은 쓰지 않았다. `Send`를 쓰면 한 superstep에 여러 노드 키가 올라오는데
`cli.py`의 스트림 루프가 `next(iter(update.items()))`로 첫 키만 읽고, 서브노드 이름에서
`STAGE_LABELS`·`STAGE_ORDER.index()`가 죽는다. `search` 노드 하나가 내부에서
`asyncio.gather`로 펼친다.

에이전트 팩토리는 **`langchain.agents.create_agent`**를 쓴다.
`langgraph.prebuilt.create_react_agent`는 deprecated고(호출하면
`LangGraphDeprecationWarning`), `langchain` v1이 `create_agent`로 흡수했다. 바뀌는 건
`prompt=` → `system_prompt=` 하나뿐이고 입력(`{"messages": [...]}`)·출력
(`result["messages"]`)·`ToolNode` 계약은 동일하다. `scout` 패키지에 `langchain` 의존성이
하나 늘었다(전이 의존성은 0 — 이미 다 깔려 있었다).

구현 중 실측으로 드러난 것 둘:

- **`checkpointer=False`로 컴파일해야 한다.** 안 주면 바깥 그래프의 `SqliteSaver`
  (동기 전용)를 물려받는데 이 에이전트는 `ainvoke`로 돌아
  `"SqliteSaver does not support async methods"`로 죽는다.
  (그때도 파이프라인은 안 죽고 `gaps`에 기록됐다 — 불변식 11이 작동한 증거다.)
- **`recursion_limit`을 호출마다 넘겨야 한다.** `create_agent`는 그래프에 **9999**를
  바인딩해둔다 — 안 넘기면 툴 루프가 사실상 무제한으로 돈다.

### 2. `web_search`에 사람 승인 게이트를 넣었다 (신규)

지금까지 설계 전체에 HITL 개념이 **없었다.** 외부 검색엔진에는 LLM이 만든 자유 서술
질의가 그대로 나가므로 사내 프로젝트 맥락이 유출될 수 있다.

```
"<질의>"를 검색하려고 합니다 확인 바랍니다
승인하시겠습니까? [y/N]
```

- **거부하면 원본 툴을 호출하지 않는다** — egress 0. 승인 문구만 띄우고 요청이 나가면
  이 기능은 장식이다. `test_search_approval.py`가 이 배선을 검사한다 (불변식 14)
- **거부 사유를 받아 에이전트에 돌려준다.** 에이전트가 사유를 반영해 질의를 고쳐
  다시 승인을 요청한다. 실측: "고유명사·제품명을 넣지 마라"고 거부하자 이후 질의가
  전부 일반 기술 용어로 바뀌었다
- 거부 3회면 차단(무한 재질의 방지), 요소당 승인 5회 예산, 비대화형이면 차단
  (`--auto-approve-search`로 열 수 있다)
- 승인 대상은 `web_search`뿐이다. npm·PyPI·GitHub는 패키지명·저장소명만 나가는
  레지스트리 조회다

**`interrupt()`를 쓰지 않았다.** LangGraph 정석 HITL이지만 (1) MCP 툴이 async 전용이라
바깥 그래프까지 `astream`+`AsyncSqliteSaver`로 다시 짜야 하고, (2) `interrupt()`는 노드를
처음부터 재실행하는데 거부→재질의 루프는 왕복마다 그 비용이 붙고, (3)
`create_agent`는 툴 콜마다 별도 태스크라 동시 interrupt에 id 맵 resume가 강제된다.
대신 `interview`가 이미 쓰는 주입 콜러블 패턴(`Approve` + `NonInteractive`)을 따랐다 —
**이 콜러블이 나중에 `interrupt()`로 갈아끼울 이음매다.**

### 함께 바뀐 것

- 테스트 **4종 → 5종** (`test_search_approval.py`). 성공 기준에 6-1번 추가
- `stages/README.md`의 "어느 단계에 LLM이 없는지" 표에서 `search의 2턴(실행)` 행이
  거짓이 되어 "`search`의 **사실 추출**"로 교체
- `CLAUDE.md` 불변식 13·14 신설, 함정 표 2행 교체, 코드 패턴 절 갱신
- STEP-05 시간 1.5h → 2h

---

## v16 (2026-09-03) — Python 3.12 → 3.14

`.python-version`·두 패키지의 `requires-python`을 3.12에서 3.14로 올렸다.
3.12로 고정했던 이유(`05-프로젝트관리.md` v15까지)는 "pydantic-core 등 네이티브
확장의 3.14 휠 유무를 걱정할 필요가 없다"였다 — 당시엔 불확실성 회피가 목적이었다.

전환 전에 PyPI를 실측 확인했다: `pydantic-core`(유일한 네이티브 확장 의존성)는
버전 2.35.0부터 최신 2.48.0까지 cp314·cp314t win_amd64 휠이 전부 존재하고, 나머지
의존성(langchain 계열·langgraph·pydantic·boto3·httpx·mcp·ddgs 등) 전부
`requires_python`에 3.13/3.14를 막는 상한이 없었다. `uv sync`로 실제 설치해
빌드 없이 90개 패키지가 그대로 깔리는 것도 확인했다 — 막는 요인이 없었다.

`uv.lock`은 `uv lock`으로 재생성했다(수동 편집 없음). 코드 변경은 없다 — 3.14가
새로 허용한 문법(PEP 758, `except A, B:` 괄호 생략)을 ruff `UP` 규칙이
`stages/interview.py`에 자동 적용한 것 외에는 전부 동일하게 동작한다.

`05-프로젝트관리.md`·`07-검증.md`의 "시스템 3.14는 건드리지 않는다"류 서술을
이 버전 기준으로 갱신했다 — 이제 uv가 조달하는 버전도 3.14라 시스템과 일치한다.

---

## v15 (2026-09-02) — web_search: DuckDuckGo → `ddgs` + Google backend

STEP-04 구현 때 `providers/search.py`를 `ddgs.text(..., backend="duckduckgo")`로
고정했다 — `ddgs`(옛 `duckduckgo-search`) 패키지 이름과 04-아키텍처.md의 "검색
엔진: DuckDuckGo" 결정을 그대로 따른 것이었다. 사용자가 바로잡았다: 패키지
선택(`ddgs`)과 그 안에서 쓸 검색엔진(backend)은 별개 결정이고, 후자는 **목적에
더 잘 맞는 걸로 고르라**는 지시였다.

`method` 후보(아키텍처 패턴·개발 접근법)의 유일한 근거라는 목적에 맞춰 실제
결과 품질을 두 시나리오로 비교했다:

- `duckduckgo` backend — 한 시나리오는 결과 0건("No results found"), 나머지도
  LinkedIn pulse·일반 블로그 위주로 신호가 약했다
- `bing` backend — 두 시나리오 다 결과가 나왔고 품질 있는 전문 블로그를 포함했다
- `google` backend — 두 시나리오 다 결과가 나왔고 Hacker News·Reddit 토론
  스레드를 일관되게 포함했다 — "이 방법이 실제로 괜찮은가"를 판단하는 근거로
  가장 값어치 있는 소스다

`google`로 바꿨다. 사설 스크래핑이라 차단 위험이 이론상 더 크지만, 프로토타입
규모(실행당 질의 몇 건)에서는 품질·커버리지 이득이 더 크다고 판단했다.
`SCOUT_EGRESS_ALLOWLIST` 기본값도 실제 요청 호스트(`www.google.com`)에 맞춰
다시 고쳤다 — v14 이전에 한 번 `html.duckduckgo.com`으로 고쳤던 것도 이번에
같이 정정된다.

`04-아키텍처.md`의 "기술 결정"·"MCP 툴 6종" 표를 이 버전 기준으로 갱신했다.

---

## v14 (2026-09-02) — CLI: 서브커맨드 없는 기본 진입점 + 단계별 배너

지금까지 `scout run "설명"`으로 설명을 인자로 넘겨야 했고, `graph.invoke()`로
파이프라인 전체를 한 번에 돌린 뒤 맨 끝에 결과 JSON을 통째로 찍었다 — 중간에
어떤 단계가 진행 중인지 알 수 없었다.

- **서브커맨드 없는 `uv run scout`가 기본 진입점**이 됐다. 실행하면 "프로젝트
  설명 입력: "으로 대화형으로 설명을 받고 바로 파이프라인을 돈다. 기존
  `run "..." --from/--stop-after/--max-components/--max-candidates`는 개발 중
  반복 실행·재현용으로 그대로 남는다 — 둘 다 같은 파이프라인 실행 로직을
  공유한다.
- **단계 경계가 눈에 보인다**: `graph.invoke()` → `graph.stream(...,
  stream_mode="updates")`로 바꿔, 노드가 끝날 때마다 "[단계] 단계를
  시작합니다."/"...종료합니다." 배너와 사람이 읽기 좋은 요약을 찍는다. 원본
  JSON은 여전히 `scout show <slug> <단계>`로 본다. 이 배너·요약은 순전히
  `cli.py`의 표현 책임이다 — `graph.py`·`stages/*.py`는 바뀌지 않는다.
- **부수 효과**: `--stop-after`가 그동안 값만 검증하고 실제로 파이프라인을
  멈추지 않던 잠재 결함을 스트림 루프 전환 김에 고쳤다. `--from`(중간부터
  재실행)은 그래프가 항상 START부터 도는 구조라 여전히 이름만 받고 실제로
  건너뛰지 않는다 — 이번 변경 범위 밖으로 남긴다.
- `report`(STEP-08) 자리에는 아직 실제 링크 대신 "다음 단계는 구현되지
  않았습니다" 안내가 나간다. `report`가 생기면 그 안내를 실제 `report.html`
  경로로 바꾸는 한 줄만 남는다 — 배너 프레임워크 자체는 그대로 재사용된다.

`02-파이프라인.md`의 "실행 흐름"·"부가 명령"을 이 버전 기준으로 갱신했다.

---

## v13 (2026-09-02) — interview: 고정 5문항 → LLM 주도 다중 턴, `Interview` 슬롯 필드 제거

STEP-02 구현·검증 후, 사용자가 "진짜 대화하듯 인터뷰하고 싶다"고 요청했다. 기존 방식은
코드가 고정된 질문 5개를 순서대로 묻고, LLM이 그 답을 `scale`·`budget_monthly_usd`·
`team_size`·`team_languages`·`deadline_months`·`data_sensitivity`·`must_haves`·
`non_goals` 8개 슬롯 필드로 나눠 담았다.

두 가지를 바꿨다.

- **대화형 다중 턴**: 질문 개수·내용을 코드가 아니라 LLM이 매 턴 판단한다. 정보가
  충분하면 스스로 대화를 끝낸다. 원문에 이미 있는 정보는 다시 묻지 않는다 — 이전
  방식에서는 "구현하지 않음"으로 명시적으로 남겨뒀던 한계다. 이 루프는 파이썬
  for-loop가 아니라 `stages/interview.py` 안의 작은 LangGraph 서브그래프
  (`ask_question → get_answer → (반복) → synthesize`, 순환은 조건 엣지)로 짰다 —
  프로젝트 전체가 LangGraph `StateGraph`로 오케스트레이션되는 것과 같은 방식을 stage
  내부 턴 루프에도 그대로 적용한 것.
- **`Interview` 스키마 슬롯 8개 제거**: "예상 규모·인원·데이터 민감도 같은 정형화된
  정보도 필요 없이 인터뷰 내용을 전달하면 되지 않을까"라는 질문에서 시작했다. 실제로
  STEP-02/03 검증 실행에서 `refined_brief`가 이미 "사내 200명... 3인 TypeScript
  팀... 메시지 전문검색과 외부 공개는 이번 범위에서 제외한다"처럼 슬롯 값을 프로즈
  안에 전부 담고 있었다 — 슬롯은 `refined_brief`와 중복이었다. `0-interview.md`가
  이미 선언해둔 원칙("조립을 한 번만 한다")과도 어긋나 있었다. 최종 `Interview`는
  `raw_description` · `refined_brief` · `assumptions` 세 필드만 남는다. "꼭 필요한
  정보는 받아야 한다"는 전제는 스키마가 아니라 **대화 단계의 질문 가이드**로 옮겨
  갔다 — `ask_question`이 여전히 규모·예산·팀·데드라인·민감도·핵심 기능·범위 제외를
  확인 대상으로 삼는다.

부수 효과: `budget_monthly_usd` 필드가 없어지면서, 그 필드 때문에 만들었던
`_recover_from_tool_call`(LLM이 JSON `null` 대신 문자열 `"null"`을 쓰는 버그를 보정하는
코드)이 통째로 필요 없어졌다.

연쇄 변경: `1-analyze.md`의 "입력" 절이 `non_goals`를 직접 참조하던 것에서
`refined_brief` 전체를 참조하는 것으로 바뀌었다. `analyze`의 판단 로직(범위 제외 →
defer/unnecessary) 자체는 그대로다 — 신호가 별도 필드에서 문장으로 옮겨갔을 뿐이다.

`0-interview.md`·`1-analyze.md`를 이 버전 기준으로 갱신했다. `stages/interview.py`·
`stages/analyze.py` 구현이 이 스키마를 따른다.

---

## v12 (2026-09-02) — STEP-01 구현 중 발견한 스키마 누락 2건 수정

`store.py`를 실제로 짜면서 `03-저장.md`의 DDL이 각 단계 문서의 Pydantic 스키마와
어긋나는 지점 둘을 발견했다. 문서만 있고 코드가 없었을 땐 안 드러났다.

- **`components`에 `priority` 컬럼 누락** — [1-analyze.md](stages/1-analyze.md)의
  `Component` 스키마와 출력 SQL은 `priority`를 포함하는데 `03-저장.md`의 DDL 스케치에는
  없었다. `search`가 상위 N개를 고르는 정렬 기준이라 없으면 안 된다
- **`verdicts`에 `unsupported_claims_json` 컬럼 누락** — `Verdict` 스키마의
  `unsupported_claims` 필드(judge가 "근거 없는 판단"이라 표시하는 정직한 출구)를 저장할
  자리가 DDL에 없었다. `pros_json`·`cons_json`·`caveats_json`과 같은 방식으로 추가

둘 다 `03-저장.md`에 반영했다. `store.py` 구현이 이 두 필드를 넣은 버전을 기준으로 한다.

---

## v11 (2026-09-02) — `python-dotenv`로 boto3 크레덴셜 간극을 메움

`.env`에 `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`를 채우고 `doctor`를 돌렸는데도
"미설정"으로 나왔다. 원인: `pydantic-settings`의 `env_file` 로딩은 **`Settings` 필드에만**
값을 채우고 `os.environ`은 안 건드린다. `boto3`는 `.env` 파일을 아예 모르고 `os.environ`만
읽으므로, 규칙 2에 따라 `Settings` 필드가 아닌 크레덴셜은 `.env`에 있어도 `boto3`가 못 찾았다.

v7에서 "`.env` 로딩이 내장이라 `python-dotenv`가 따로 필요 없다"고 썼던 게 **`Settings` 필드에만
해당하는 얘기였다** — boto3처럼 `Settings`를 거치지 않고 `os.environ`을 직접 읽는 라이브러리는
예외였다. 실측(`doctor` 실행)으로 드러남.

- `scout` 패키지에 `python-dotenv` 명시 의존성 추가 (`pydantic-settings`의 전이 의존성으로
  이미 설치돼 있었지만, 코드가 직접 import하므로 명시해야 안전하다)
- `scout/cli.py`의 `@app.callback()`에서 `load_dotenv()`를 서브커맨드 실행 전에 호출
- `08-설정.md`에 "★ `boto3`는 `.env`를 모른다" 절 추가

이 절 하나로 STEP-00의 남은 완료 기준 2개(`ListFoundationModels`, Sonnet 1회+4병렬 호출)가
실제 AWS 계정으로 통과했다.

---

## v10 (2026-09-02) — Bedrock 인증을 Access Key 방식으로 확정

[07-검증](07-검증.md) M0 7번이 미결이었던 질문("사내 계정이 SigV4인지 Bedrock API key인지")이
**Access Key 방식**(`AWS_ACCESS_KEY_ID` · `AWS_SECRET_ACCESS_KEY` · `AWS_DEFAULT_REGION`)으로
확정됐다. SigV4 프로필 · Bedrock API key(`AWS_BEARER_TOKEN_BEDROCK`) 경로는 걷어냈다 —
지금 안 쓰는 코드를 남겨둘 이유가 없다.

- `AWS_REGION` → `AWS_DEFAULT_REGION`. `Settings.aws_region`은
  `Field(validation_alias="AWS_DEFAULT_REGION")`으로 매핑 (규칙 8은 그대로 — 표준 이름이라
  boto3 기본 체인이 그대로 읽는다)
- `AWS_PROFILE` · `AWS_BEARER_TOKEN_BEDROCK` 필드·환경변수 제거. `aws_profile`이 없어지며
  `llm.py`의 `credentials_profile_name` 전달도 같이 사라졌다 — boto3가 `AWS_ACCESS_KEY_ID` /
  `AWS_SECRET_ACCESS_KEY`를 환경에서 그대로 집는다 (규칙 9는 그대로 — 크레덴셜은 여전히
  `Settings`에 담지 않는다)
- `doctor`의 존재 여부 체크 대상이 `AWS_BEARER_TOKEN_BEDROCK` 하나에서
  `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` 둘로 바뀜 (값은 여전히 안 찍는다)

`08-설정.md` · `07-검증.md` · `002/STEP-00-환경.md`의 변수명을 전부 갱신했다.

---

## v9 (2026-09-02) — `necessity` 검증 테스트 추가 (테스트 4종)

SERVICE.md를 쓰면서 **증거의 비대칭**이 드러났다. 이 도구의 차별점은 둘인데,
검증 강도가 달랐다.

| 차별점 | v8까지의 검증 |
|---|---|
| judge가 사실을 지어낼 수 없다 (grounding) | `test_grounding.py` — 자동·결정론적 |
| **안 만들어도 되는 걸 알려준다** (`necessity`) | **육안 확인뿐** |

`necessity`를 "가장 값어치 있는 필드"라고 세 곳에 써놓고 자동 검증이 없었다.
게다가 완료 기준 "최소 1개 걸러짐"은 약했다 — **걸러놓고 `search`가 그냥 다 조사해도
통과**한다. 기능이 아무 효과 없이 장식으로 남을 수 있었다.

### `test_necessity_wiring.py` 신규 (테스트 3종 → 4종)

`Analysis` 출력을 고정 픽스처로 주고 **LLM 없이 코드 경로만** 검사한다.

```
1. defer/unnecessary 요소가 search 입력 목록에 들어가지 않는다
2. 그 요소가 report 의 "지금 만들지 않아도 되는 것" 섹션에 렌더링된다
3. 걸러진 요소가 0개면 경고가 출력된다
```

`test_stale_regression.py`와 같은 성격이다 — **판단이 최종 결과를 실제로 바꾸는지.**
LLM을 부르지 않으므로 빠르고 결정론적이다. 네 테스트 모두 이 성질을 갖는다.

### 판단 품질과 배선을 분리했다

LLM의 판단 품질("전문검색이 정말 불필요한가")은 결정론적으로 검증할 수 없다.
그래서 성공 기준을 둘로 나눴다.

| | 무엇을 보는가 | 방법 |
|---|---|---|
| 성공 기준 4번 | **배선** — 걸러낸 게 실제로 걸러지나 | 자동 (`test_necessity_wiring.py`) |
| 성공 기준 7번 | **판단 품질** — 그 걸러내기가 타당한가 | 육안 |

7번에 경고를 명시했다: essential인 걸 `unnecessary`로 잘못 분류하면
**테스트는 통과하지만 도구는 해롭다.**

### 함께 고친 문서 오류 2건

- `001/README.md` — "성공 기준 6개"라고 써 있었으나 실제로는 9개였다 (지금 10개)
- `001/07-검증.md` — 마지막 문장의 마침표 두 개 (`증거다..`)

성공 기준이 9개 → **10개**, 번호가 재정렬됐다 (`test_necessity_wiring`이 4번으로 삽입).
`1-analyze.md` · `5-report.md`의 "성공 기준 6번" 참조를 7번으로 갱신했다.

일정 영향은 없다 — STEP 09의 1h 안에서 흡수한다 (테스트가 30분 규모).

---

## v8 (2026-09-02) — judge가 종합 점수를 매긴다

`evaluate`가 **순위만** 냈다. v6에서 5기준 점수를 2기준(코드 계산)으로 줄일 때
LLM 점수를 통째로 없앴는데 **그게 과했다.**

- 순위만 있으면 **1위와 2위가 근접한지 압도적인지 알 수 없다.**
  "socket.io가 1위"와 "socket.io 4 vs ws 3"은 의사결정에서 완전히 다른 정보다
- `winner_reason`이 점수 차이를 인용할 수 없었다
- 확정 스택 표에 보여줄 숫자가 없어 비교가 시각적으로 죽었다 (v6에서 종합 점수를 지운 결과)

### 복원한 것과 복원하지 않은 것

| | 조치 |
|---|---|
| LLM 종합 점수 (`overall`) | **복원** — judge가 직접 매긴다 |
| 기준별 LLM 점수 (`fit`·`team_fit`·`exit_cost`) | 복원 안 함 |
| 가중치 (`interview` 도출) | 복원 안 함 — 배수 근거가 임의적인 문제는 그대로다 |
| 가중 합산 공식 | 복원 안 함 — `overall`은 judge의 판단이다 |

핵심 차이: 점수를 **곱하고 더해서** 만들지 않고, judge가 근거를 보고 **매긴다.**

### 점수 3개 (계산 2 + 판단 1)

| 기준 | 산출 | `source` |
|---|---|---|
| `maturity` · `risk` | 코드 계산 | `computed` |
| `overall` | **judge** | `judged` |

**LLM 점수를 하나만 둔 이유**: `fit`·`team_fit`을 따로 매기게 하면 judge가 그것들을 평균해
`overall`을 낼 유혹이 커진다. 하나만 매기게 하면 그 위험 자체가 사라진다.
그리고 `score_reason` 한 문장이 숫자 두 개보다 정보가 많다 —
"요구 충족은 되지만 팀에 낯설다"는 `fit=5, team_fit=2`보다 유용하다.
부수 효과로 리포트 막대가 3개라 읽힌다.

### `overall`은 평균이 아니다 — 프롬프트에 반례를 박는다

산술 평균으로 내면 그건 가중치 없는 가중 합산일 뿐이다. 반례 4개를 명시했다
(`maturity 5`라도 요구 미충족이면 2 / `risk 1`이면 2를 못 넘음 / `unavailable`이면 낮춤 /
`refined_brief` 제약이 반영돼야 함).

**이중 안전망은 유지된다** — `maturity`·`risk`가 계산된 숫자로 judge 프롬프트에 들어간다.
judge가 낡은 사실을 무시하더라도 `maturity=1`이 프롬프트에 박혀 있다.

### 신규 필드

- **`CandidateScore`** — `overall` + `score_reason`(후보마다 왜 그 점수인지, 근거 인용 필수)
- **`margin`** (`decisive` | `close`) — `overall` 차이 ≤1이면 `close`.
  보고서에 "근접 — 2위도 합리적 선택"을 표시한다. **점수를 매기면 공짜로 얻는 정보**이고,
  순위만 있을 때는 낼 수 없었다
- **`scores.reason`** 컬럼 — 계산 점수의 근거 요약과 judge의 `score_reason`을 같은 자리에
- `winner_reason` 요구가 2개로: 제약 인용 **+ 2위와의 점수 차이**

### 보고서

- 확정 스택 표에 `overall` 막대 복원 + `close` 시 `[근접]` 배지
- 요소별 비교 막대 3개, `computed`/`judged`/`근거 없음` 배지 3종
  (v6에서 지운 `judged` 배지를 되살렸다)
- **`score_reason`을 막대 바로 아래** 둔다 — 숫자와 이유가 떨어져 있으면
  읽는 사람이 숫자만 보고 넘어간다

### 일정

`evaluate` 0.75h → **1h**. 합계 13.75h → **14h** (예산 16.25h, 여유 2.25h).
LLM 호출 수는 그대로다 — 출력 스키마만 커진다.

---

## v7 (2026-09-02) — 설정 관리 문서화 (`08-설정.md` 신설)

설계 문서 전체에 **설정 관리가 빠져 있었다.** `.env.example`은 002/STEP-00에 파일명만 있고
내용 명세가 없었고, `config.py`는 "모델 ID · 리전 · 동시성 상수"라고만 써 있어 **값을 어디서
읽는지**가 없었다. 설정 항목 16개가 7개 문서에 흩어져 있었다.

### `08-설정.md` 신설

- **설정 항목 단일 목록** — 앱 전용 10개 / MCP 서버 전용 6개로 나눈 표
- `.env.example` 전문 + `.gitignore` (지금까지 `.gitignore` 언급이 **아예 없었다**)
- `config.py`를 `pydantic-settings` `BaseSettings`로. 타입 검증과 **필수 변수 누락을
  실행 전에 잡는 것**이 공짜로 온다. `python-dotenv`가 불필요해져 실질 의존성 증가는 0
- 우선순위 명시: CLI 플래그 > 환경변수/`.env` > `Settings` 기본값

### AWS 변수는 표준 이름을 쓴다 — `langchain-aws` 전제

`ChatBedrockConverse`가 내부적으로 boto3를 쓰므로 표준 변수를 boto3 자격 체인이 알아서 집는다.

- **`SCOUT_` 접두사를 AWS 변수에 붙이지 않는다.** `SCOUT_AWS_REGION` 같은 이름을 만들면
  boto3 기본 동작이 깨지고 손으로 배선해야 한다. `SCOUT_`는 앱 고유 설정에만
- **크레덴셜을 `Settings`에 담지 않는다.** `AWS_BEARER_TOKEN_BEDROCK`을 읽어서 넘기면
  크레덴셜이 우리 객체·로그·예외 트레이스에 들어올 수 있다. boto3가 환경에서 직접 집게 두고
  `doctor`는 **존재 여부만** 확인한다(값은 찍지 않는다)
- `aws_profile`이 `None`이면 boto3 기본 체인이 돈다 →
  **사내 환경이 SigV4든 API key든 코드가 같다**

### ★ 크레덴셜 경계를 stdio에서 실제로 강제한다

지금까지 "`GITHUB_TOKEN`은 MCP 서버 쪽에만"이라고 **세 곳에 써놓고 방법을 말하지 않았다.**
stdio는 부모 프로세스의 환경을 자식이 물려받으므로 그냥 두면 경계가 없다.

`MultiServerMCPClient`의 stdio 설정에 `env`를 명시적으로 지정해 통과할 변수만 남긴다 →
**MCP 서버 프로세스에 `AWS_*`가 존재하지 않는다.**

정직한 한계도 적었다: 앱은 `.env` 전체를 읽으므로 `GITHUB_TOKEN`을 메모리에 갖는다.
**stdio에서는 경계가 논리적이고, streamable-http로 바꾸면 물리적이 된다.**

### 문서 정리

이 프로젝트는 **Bedrock(`langchain-aws`) 전용**이다. 다른 인증 경로를 언급하던 잔여 서술을
`07-검증.md`에서 걷어냈다(크레덴셜 표 한 행, 비용 절의 단가 비교).
비용 절은 "단가는 AWS 콘솔에서 확인한다"로 바꿨다.

### M0 확인 항목 추가 (7번)

**Bedrock 인증 방식** — 둘 다 없으면 그 자리에서 막히므로 STEP 00의 첫 확인 대상.
`doctor`가 찍을 5가지를 명시했다(`sts get-caller-identity` · API key 존재 여부 ·
**boto3/langchain-aws 버전** · `ListFoundationModels` · 1회+4병렬 호출).

세 번째가 중요하다 — Bedrock API key 지원은 boto3 버전에 의존하고,
변수명이 `AWS_BEARER_TOKEN_BEDROCK`인지도 이때 확정한다.

### 002 반영

`config.py`를 STEP 01 → **STEP 00으로 이관**(`doctor`가 모델 ID를 읽어야 한다).
STEP 00 완료 기준에 설정 검증 3개 추가 — `AWS_REGION` 없이 실행하면 시작 시 실패하는지,
타입 오류가 잡히는지, `git status`에 `.env`가 안 뜨는지.

---

## v6 (2026-09-02) — 가중치 제거, `interview`는 구체화로

개발 범위를 더 줄였다. 없앤 건 **평가 가중치**고, 그 자리를 LLM-as-judge가 대신한다.

### 왜 가중치를 뺐나

| 문제 | 설명 |
|---|---|
| 배수의 근거가 임의적 | 왜 `team_fit ×1.5`이고 1.3이 아닌가. 2일 안에 튜닝할 방법이 없다 |
| 대응 항목이 없는 제약이 갈 곳을 잃음 | 예산은 5기준 중 어디에도 대응하지 않았다 (v4에서 발견, 미해결로 남아 있었다) |
| 같은 정보를 두 번 해석 | `fit`·`team_fit`·`exit_cost` 점수의 재료가 이미 `verify`의 `pros`/`cons`/`caveats`에 다 있었다 |

### `interview`: 가중치 도출 → 요청 구체화

- `Interview.weights` **삭제**. `runs.weights_json` 컬럼 삭제
- **`refined_brief`** 신규 — 되묻기 답을 합친 3~5문장 명세.
  `analyze`·`verify`·`evaluate` 프롬프트에 **그대로** 들어간다.
  제약조건을 단계마다 필드별로 재조립하지 않는다
- **`must_haves`** / **`non_goals`** 신규.
  `non_goals`가 `analyze`의 `defer` 판단에 직접 흐른다 —
  사용자가 "검색은 나중에"라고 말했으면 그게 근거가 된다.
  가중치라는 간접 경로보다 정확하다
- "가중치 도출" 절과 "예산은 가중치로 가지 않는다" 절 삭제 (≈50줄)

### `evaluate`: 가중 합산 → judge 순위 판단

| 기준 | v5 | v6 |
|---|---|---|
| `maturity` | 코드 계산 | **유지** |
| `risk` | 코드 계산 | **유지** |
| `fit` · `team_fit` · `exit_cost` | LLM 점수 | **삭제** |

- 순위는 요소별 LLM 1회. 입력은 계산 점수 + `Verdict` 전체 + `refined_brief`
- **`ElementPick`** 신규 — `ranking` · `winner` · `winner_reason` · `runner_up_note`.
  `winner_reason`에 `refined_brief`의 제약이 인용돼야 한다 (성공 기준 8번)
- `rubric.py`에서 가중치 기본값·조정 규칙·정규화가 사라지고 점수 공식만 남는다
- `scores.source`가 `computed | judged` → **`computed | unavailable`**.
  `method` 후보는 `maturity`를 계산할 숫자가 없는데, 0으로 두면 실제보다 불리해 보인다.
  `NULL` + `unavailable`이면 **낮은 게 아니라 없는 것**이 된다

### 유지한 것 — `maturity`·`risk` 코드 계산

사라진 건 가중 합산 공식이고 계산 자체는 남겼다. 없애면 `test_stale_regression`의
이중 안전망(judge가 낡은 사실을 무시해도 계산이 잡아냄)이 깨져 핵심 가설의 증거가
judge 하나에만 걸린다. 계산된 점수는 judge 프롬프트에 숫자로 들어간다.

### 보고서 변화

- "적용된 가중치" 섹션 → **"구체화된 명세"(`refined_brief`) + "이번 범위 밖"(`non_goals`)**
- 확정 스택 표의 **종합 점수 삭제** — 가중 합산이 없으니 보여줄 숫자가 없다.
  대신 `winner_reason` 한 줄. 순위의 근거가 숫자가 아니라 judge의 문장이므로 그 문장을 보여준다
- 요소별 비교의 막대가 5개 → **2개**(`maturity`·`risk`), 1위·2위에 판단 문장을 붙인다

### 일정

`evaluate` 1h → **0.75h**. 합계 8.5h → **8.25h**.
LLM 호출 수는 그대로다 (`evaluate`가 요소당 1회). 줄어든 건 구현할 로직이다.

성공 기준 2개 추가: 7번(`refined_brief`가 원문 복사가 아닌지),
8번(`winner_reason`에 제약조건이 인용되는지).

---

## v5 (2026-09-02) — 프로토타입 규모 축소 + HTML 보고서

### 규모를 상수가 아니라 플래그로

한 번 돌리고 눈으로 확인하는 주기가 짧아야 한다는 이유로 기본 규모를 크게 줄였다.

| | v4 | v5 |
|---|---|---|
| `search` 통과 요소 | essential/valuable 전부 (6~8개) | **상위 3개** (`--max-components`) |
| 요소당 후보 | 3~5개 | **2~3개** (`--max-candidates`) |
| 총 후보 | 30~40개 | **8~10개** |
| judge 호출 | 30~40회 | **8~10회** |
| dossier 수집 | ~3분 | ~1분 |
| 1회 실행 토큰 | 입력 300~400k | **100~150k** |

- `Component`에 **`priority`** 필드 추가. LLM이 "무엇이 이 프로젝트의 심장인지"를 매기고,
  `search`는 `priority` 상위 N개만 받는다
- **도출과 통과를 분리했다** — 요소는 6~10개 전부 `components`에 저장하고 통과만 3개.
  덕분에 `necessity` 기능이 살고, 통과 못 한 요소도 보고서에
  "이번에 다루지 않음"으로 남는다. 조용히 사라지지 않는다
- 규모를 CLI 플래그로 뺐으므로 실전에서는 `--max-components 8 --max-candidates 5`

**부수 효과**: 후보 10개면 MCP 호출이 30건 정도라 GitHub 토큰 없이 1회 실행이 된다
(미인증 60req/h).

**트레이드오프를 문서에 명시했다**: 요소당 2~3개면 사실상 "1위 + 대안 1~2개"라 비교의 값이
얕다. 파이프라인 검증에는 충분하지만 실제 의사결정에는 플래그를 올려야 한다.

### 보고서를 마크다운 → 단일 HTML

마크다운 표로는 점수 비교가 눈에 안 들어온다. `maturity 5 · risk 3`을 숫자로 읽는 것과
막대 길이로 보는 것은 다르다.

- 출력이 `report.md` → **`report.html`** (마크다운은 만들지 않는다.
  두 형식을 유지하면 둘 다 반쯤 된다)
- **self-contained 단일 파일** — 외부 CDN 없음, JS 0줄, 인라인 CSS.
  사내 환경에서 CDN이 막힐 수 있고, 파일 하나로 공유돼야 "쉽게 볼 수 있다"가 성립한다
- JS 없이 하는 것: 점수 막대는 CSS `width`, 접히는 섹션은 `<details>`,
  배지는 CSS 클래스, 다크모드는 `prefers-color-scheme`
- 정렬·필터 UI는 넣지 않는다 — 요소 3개 규모에서 정렬할 것이 없고, JS를 들이는 지점이다
- `jinja2` + `templates/report.html.j2`. HTML을 f-string으로 짜면 Day 2를 잡아먹는다.
  `langchain-core`가 이미 끌어올 수 있어 실제 추가 의존성은 0일 수도 있다 — M0 확인 항목 7번
- 터미널에는 CLI가 6줄 요약을 찍는다 (확정 스택 + 리포트 경로)
- 새 성공 기준 7번: 브라우저 육안 확인 + **네트워크를 끊고도 레이아웃이 안 깨지는지**
  (CDN 의존이 없다는 증거)

### 일정 재배분

`verify` 1.5h → 1.25h (호출이 적어 반복이 빠르다). 그만큼을 HTML 템플릿에 옮기고
`evaluate`와 `report`를 별도 슬롯으로 분리했다. 합계 8.5h 유지.

절단선에 4번 "`report.html`의 꾸밈"을 추가했다 (다크모드·배지 색상이 먼저 잘린다).

---

## v4 (2026-09-02) — 문서 분리

한 파일 716줄이 되어 폴더로 격상하고 주제별로 나눴다.

- `001_....md` (단일 파일) → `001_.../` (폴더 + 15개 파일)
- 6단계 각각의 상세 문서를 `stages/`에 신설.
  **`interview` 상세는 새로 쓴 내용이다** — 이전 문서에는 이 단계의 세부가 없었다
- 진입점 `README.md` 추가 — 목적별로 어디부터 읽을지 안내
- 본문에 섞여 있던 v1/v2 비교 서술을 전부 이 파일로 이동.
  처음 읽는 사람에게 이력은 방해다
- 중복 제거: grounding SQL(저장 ↔ verify), Bedrock 제약 목록(2곳),
  dossier 설명(3곳), 검증 전략 표 ↔ 성공 기준, `necessity` 설명(2곳)

### 이번에 드러난 설계 구멍

`ops_cost` 기준을 잘라낸 결과 **예산이 가중치에 반영될 자리가 없다**는 게 드러났다.
`interview`가 예산을 묻는데 5개 기준 어디에도 반영되지 않는다.

당장은 두 간접 경로로 흐르게 하고 문서에 명시했다:

1. `analyze`의 필요성 판단 — 예산이 빡빡하면 "자체 인프라 구축"이 `unnecessary`가 된다
2. `verify` judge 프롬프트의 제약 조건 — judge가 호스팅 비용을 `cons`에 적는다

`ops_cost` 기준을 되살리는 건 v5 후보다.

### 가중치 계산 예시 정정

이전 문서의 예시(`fit .20 · exit_cost .15 · risk .10`)가 조정 규칙에서 실제로 나오는 값과
맞지 않았다. 규칙을 명시하고 예시를 계산 결과로 교체했다 →
`team_fit .30 · maturity .25 · fit .21 · risk .12 · exit_cost .12`

---

## v3 (2026-09-02) — sqlite 저장 계층 + 용어 정의

- 산출물을 **단계별 JSON 파일 → `runs/<slug>/scout.db` 하나**로 통합.
  표준 라이브러리 `sqlite3`, ORM 없음. `artifacts.py` → `store.py`
- `:memory:` 대신 **파일**을 선택. 코드 차이는 연결 문자열 하나지만, dossier 수집이 가장
  비싼 단계라 `verify` 프롬프트를 반복 튜닝할 때 `--from verify`로 들어갈 수 있어야 한다.
  인메모리 sqlite의 커넥션 수명 · asyncio 공유 제약도 피한다
- **grounding 검증이 SQL 한 줄**이 됐다
  (`citations LEFT JOIN facts WHERE f.fact_id IS NULL`).
  파이썬 집합 차집합보다 깔끔하다
- `scores.source` 컬럼 추가 — 어느 점수가 계산(`computed`)이고 어느 게 판단(`judged`)인지
  행마다 기록돼 보고서에서 구분 표시 가능. JSON 중첩이면 따로 설계해야 했던 것
- **용어 정의** 절 추가 (요소 / 후보 / dossier / 사실 / 판정 / grounding).
  `dossier`가 무슨 뜻인지 문서 어디에도 없었다
- Day 2 8h → 8.5h. 초과분은 절단선 1~2번에서 흡수

---

## v2 (2026-09-02) — LLM-as-judge

v1은 `verify`를 결정론적 사실 수집(LLM 0회)으로 설계했다. v2에서 **LLM-as-judge**로 바꿨다.

- `verify`가 판정을 하고, **사실 수집은 `search`로 이동**했다
- `Fact.id` 기반 **닫힌 인용 집합** + `grounding.py` 검증 도입.
  judge가 URL을 자유롭게 쓰면 환각이 가능하지만 닫힌 id 집합에서는 불가능하다.
  v1의 `Evidence` 스키마보다 오히려 개선이다
- `analyze`에 **`necessity`** 추가 — 안 만들어도 되는 요소를 걸러낸다
- 후보 `kind`를 `method` / `software` / `library` 3종으로 확장,
  dossier 수집을 kind별로 라우팅
- `evaluate`에서 `maturity`·`risk`만 코드 계산으로 유지 (판정과 계산의 이중 안전망)
- 테스트 2종 → 3종 (`test_grounding.py` 추가)
- M0 확인 항목에 Bedrock 동시 호출 쿼터 추가 (judge 30~40회 병렬)

### 절단선 순서 정정 — v1 판단의 뒤집힘

v1은 **`web_search`(DuckDuckGo)를 절단선 1순위**로 뒀다. 레지스트리 API만으로 충분하다고
봤기 때문이다.

그런데 후보에 `method`(아키텍처 패턴, 개발 접근법)가 포함되면 그건 조회할 레지스트리가 없다 —
**웹검색이 유일한 근거다.** 절단 대상에서 빼고 순서를 다시 짰다:

```
v1:  web_search → osv_query → interview 되묻기
v2:  osv_query → method 후보 → grounding 재판정 루프 → interview 되묻기
     (web_search 와 grounding 검출은 버리지 않는다)
```

---

## v1 (2026-09-02) — 초안

- 6단계 파이프라인, `verify` 결정론(LLM 0회), 평가 기준 5개
- uv 워크스페이스로 인터넷 출구 격리, ruff `TID251` 2차 방어
- 단계별 JSON 파일 산출물

### v1에서 정해져 지금까지 안 바뀐 것

- **인터넷 출구를 MCP 서버 하나로 격리** — 사내 보안 요구를 구조로 옮긴 것
- **uv 워크스페이스로 의존성 수준에서 경계 강제** — "규율로 지킨다"가 "설치가 안 된다"로
- **`report`를 LLM이 쓰지 않는다** — 2일 예산의 최대 절약
- **단계명 = 모듈명 = CLI 인자** 규칙
- Day 1은 MCP 서버, Day 2는 파이프라인
