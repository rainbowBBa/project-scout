# 2 · search

← [단계 목록](README.md) · 이전: [1-design](1-design.md) · 다음: [3-verify](3-verify.md)

**구현 방법·소프트웨어·라이브러리를 조사하고, 판정에 쓸 사실(dossier)까지 모은다.**
모듈 `scout/stages/search.py` · 테이블 `candidates` `facts` `gaps` · LLM 2회/요소 + MCP

---

## 목적

두 가지를 한다.

1. 각 요소를 구현할 **후보**를 찾는다
2. 각 후보에 대해 **dossier**(판정용 사실 자료철)를 모은다

2번이 이 단계의 무게중심이다. `verify`의 judge는 dossier 밖을 인용할 수 없으므로,
**여기서 모으지 않은 사실은 판정에 영향을 줄 수 없다.**

---

## 입력

`components` 테이블에서 `necessity IN ('essential', 'valuable')`이고
`needs_comparison = true`이고 **`alternatives`가 2개 이상**인 결정 지점을 `priority`
순으로 정렬해 **상위 3개**만
(`--max-components`, 기본 3). `defer`/`unnecessary`, 설계에서 이미 닫힌 결정,
우선순위가 밀린 요소는 이 단계에 들어오지 않는다 — [1-design](1-design.md) 참조.

`interview` 제약조건도 함께 넣는다 — 질의 생성 방향을 잡는 데 쓴다.

### 결정 지점이 조사 지시를 들고 온다

`design`이 요소마다 네 값을 채워 보낸다. 에이전트 태스크 프롬프트가 이걸 그대로 받는다.

| 값 | 에이전트에게 하는 일 |
|---|---|
| `decision_question` | **무엇을 고를 것인가** — 조사의 목표를 한 문장으로 준다 |
| **`alternatives`** | **★ 최소 커버리지** — 이 보기들은 반드시 후보로 올린다 |
| `constraints` | **후보 필터** — 이 조건을 못 지키는 후보는 찾아도 의미가 없다 |
| `search_hints` | **질의 씨드** (영어 기술 어휘) |
| `role_in_design` · `approach_notes` | 설계 안에서 이 조각이 맡는 자리와 방향 |

### `alternatives`는 최소이고 상한이 아니다

`design`이 뽑은 보기를 **하나도 빠뜨리지 않고** 후보로 올린다. 조사하다 더 나은 것을
찾으면 추가해도 된다.

**코드가 커버리지를 검사한다** — 대안 이름이 후보에 하나도 안 걸리면 `gaps`에 남긴다.
실측에서 질문이 `"Next.js vs Vite+React"`였는데 **Next.js가 후보에 없었고**, 그 사실이
어디에도 안 남아 보고서만 보면 알 수 없었다 ([CHANGELOG v26](../CHANGELOG.md)).
`search_hints`가 빈 것을 `gaps`로 잡는 것과 같은 성격이다.

`search_hints`가 없으면 이 단계는 한국어 추상 명사구(`실시간 메시지 전달`)만 들고
`npm_search`를 부르게 되고, 레지스트리에서 신호가 나오지 않는다. 그래서 `design`은
이 값을 비워 보내지 않는다.

### 프로토타입 규모

| 파라미터 | 기본 | CLI 플래그 |
|---|---|---|
| 통과 요소 수 | 3 | `--max-components` |
| 요소당 후보 수 | 3 | `--max-candidates` |
| → 총 후보 | **8~10개** | |

풀 규모로 돌리려면 `--max-components 8 --max-candidates 5` (후보 30~40개).
기본값을 작게 둔 이유는 프로토타입에서 **한 번 돌리고 결과를 눈으로 확인하는 주기**가
짧아야 하기 때문이다. 후보 40개면 dossier 수집 3분 + judge 40회를 매번 기다린다.

**트레이드오프**: 요소당 2~3개면 사실상 "1위 후보 + 대안 1~2개"라 비교의 값이 얕다.
파이프라인이 작동하는지 검증하는 데는 충분하지만, 실제 의사결정에 쓰려면 플래그를 올려야 한다.

---

## 스키마

```python
class Fact(BaseModel):
    id: str              # "npm.last_release" · "gh.last_commit" · "osv.vulns" · "web.3"
    label: str           # "마지막 릴리스"
    value: str           # "2021-01-14 (1,690일 전)"
    url: str | None
    retrieved_at: str

class Candidate(BaseModel):
    component: str
    name: str            # "socket.io" · "PostgreSQL LISTEN/NOTIFY" · "이벤트 소싱"
    kind: Literal["method", "software", "library"]
    what_it_is: str
    dossier: list[Fact]      # ★ judge가 인용할 수 있는 유일한 사실 집합
    dossier_gaps: list[str]  # ★ 못 구한 항목 — "GitHub 조회 실패", "레지스트리 없음"
```

### `Fact.id`가 이 설계의 핵심

judge는 `citations: ["npm.last_release", "osv.vulns"]`처럼 **id로만** 인용한다.
URL을 자유롭게 쓰게 하면 환각이 가능하지만, 닫힌 id 집합에서는 불가능하다.
`grounding.py`가 SQL 조인으로 대조한다 — [03-저장](../03-저장.md).

id는 `<출처>.<항목>` 규칙으로 만든다.

| id | 출처 |
|---|---|
| `npm.last_release` `npm.license` `npm.deprecated` | `npm_package` |
| `pypi.last_release` `pypi.yanked` | `pypi_package` |
| `gh.last_commit` `gh.archived` `gh.contributors` `gh.stars` `gh.issue_close_rate` | `github_repo_health` |
| `osv.vulns` `osv.max_severity` | `osv_query` |
| `web.1` `web.2` `web.3` … | `web_search` (스니펫 순번) |

---

## kind별 dossier 수집 라우팅 — **코드의 보강 경로**다

아래 표는 `topup_dossier`가 **코드로** 채우는 경로다. 에이전트에게 "이 kind면 이 툴을
써라"고 지시하지 않는다 — 그렇게 하면 툴 선택이 프롬프트에 굳고, 실측에서 npm만 부르는
편향이 났다 ([CHANGELOG v25](../CHANGELOG.md)). 에이전트는 자율로 고르고, 빠진 필수
사실만 코드가 결정론적으로 메운다.

| kind | 예 | 수집 경로 |
|---|---|---|
| `library` | socket.io, langchain | `npm_package`/`pypi_package` + `github_repo_health` + `osv_query` + `web_search` |
| ↳ 순서 | | `osv_query`는 **레지스트리 뒤에** 온다 — 버전을 알아야 물을 수 있다 |
| `software` | PostgreSQL, Redis, Meilisearch | `github_repo_health` + `web_search` (+ 있으면 레지스트리) |
| `method` | 이벤트 소싱, CQRS, PG LISTEN/NOTIFY | `web_search`만 |

**`method`는 조회할 레지스트리가 없다.** 이건 결함이 아니라 사실이고, `dossier_gaps`에
명시적으로 드러나야 한다. judge가 "근거가 웹 스니펫 3건뿐"이라는 걸 알고 판단해야 한다.

**취약점은 버전을 특정해서만 묻는다.** `osv_query`가 표에서 `npm_package`/`pypi_package`
뒤에 오는 것은 순서가 아니라 **의존**이다 — 레지스트리에서 읽은 `latest_version`이 없으면
조회 자체를 하지 않고 `gaps`에 남긴다. 버전 없는 조회는 이미 고쳐진 과거 취약점까지
세어 오래 유지된 패키지를 위험해 보이게 한다 ([04-아키텍처](../04-아키텍처.md)
`osv_query` 항목). 안 묻는 쪽이 틀린 숫자보다 낫고, 그때 `risk`는 "osv 미조회 — 취약점
항목 제외" 경로로 간다.

### `dossier_gaps`를 반드시 채운다

```
socket.io         gaps: []
PG LISTEN/NOTIFY  gaps: ["레지스트리 없음 (method)"]
이벤트 소싱        gaps: ["레지스트리 없음 (method)", "GitHub 저장소 없음"]
sockjs            gaps: ["GitHub 조회 실패 — 레이트리밋"]
```

이 필드가 `verify`의 `confidence` 판정에 직접 쓰인다.
gaps가 핵심 항목을 포함하면 judge는 `confidence: low`를 내야 한다.

---

## 동작 — ReAct 에이전트

요소마다 `langchain.agents.create_agent` 하나를 돌린다. 에이전트가 툴을 직접 고르고,
여러 번 부른다. (`langgraph.prebuilt.create_react_agent`는 deprecated —
`langchain` v1이 `create_agent`로 흡수했다. 바뀌는 건 `prompt=` → `system_prompt=`
하나뿐이고 입출력 계약은 같다.)

```
요소 "실시간 메시지 전달"

  ReAct 루프   agent ⇄ tools
               npm_search · npm_package · pypi_package
               github_repo_health · web_search(승인 게이트)
               → recursion_limit 16으로 상한 (superstep 수 — 툴 호출 ~8회)
                 한도에 걸려도 부분 기록으로 후보를 뽑는다 (agentkit.run_agent_loop)

  코드         ToolMessage 원본에서 Fact 추출 (LLM 개입 없음)
  LLM          후보 정리 · 중복 제거 (구조화 출력)
  코드         kind별 필수 사실 누락분 보충
```

### ★ 사실은 툴 원본에서만 나온다

에이전트는 **어떤 툴을 부를지만** 정한다. `Fact.value`는 에이전트가 쓴 문장이 아니라
`ToolMessage`의 원본 payload에서 코드가 파싱한다. 사실을 후보에 연결하는 것도
코드다 — 툴 호출 인자와 후보 이름을 대조한다 (`call_matches`).

이 경계가 무너지면 judge가 인용하는 dossier 자체가 LLM 생성물이 되고,
**grounding 검사는 통과하는데 사실은 환각인** 최악의 상태가 된다.
[3-verify](3-verify.md)의 인용 강제가 지탱하던 주장이 뿌리에서 깨진다.

### 왜 ReAct 에이전트인가 — v14까지의 판단이 뒤집힌 경위

v14까지 이 문서는 "3턴 파이프라인(에이전트 아님)"이었다. 근거는 하나였다 —
*"DuckDuckGo 스니펫 품질이 나쁘고 모델이 Sonnet이라, 에이전트에 검색을 맡기면 헤맨다."*

**그 전제가 v15에서 이미 무너져 있었다.** 검색 backend를 duckduckgo → google로 바꾼
이유가 바로 "duckduckgo는 결과 0건인 시나리오가 있었고 신호가 약했다"는 실측이었다.
품질이 ReAct를 막던 이유였는데, 그 품질 문제를 v15가 해결한 뒤에도 결론만 남아 있었다.

실측 결과 에이전트는 헤매지 않는다 — 요소 하나에 npm_search로 후보를 찾고,
npm_package·github_repo_health로 사실을 모으고, 웹검색으로 method 후보를 조사하는
멀티 툴 콜링이 안정적으로 돈다. 오히려 **너무 많이 검색하는 것**이 문제여서 예산으로
막는다(아래).

### 동시성

| 층 | 제한 |
|---|---|
| 요소 fan-out | `search` 노드 내부의 `asyncio.gather` |
| MCP 호출 | `Semaphore(SCOUT_MCP_CONCURRENCY)` |
| MCP 서버 | 자체 토큰버킷 레이트리미터 (이중 방어) |
| 요소당 웹검색 | **5회** (승인 프롬프트 폭주 방지, `SCOUT_SEARCH_WEB_SEARCHES`) |

**`Send` fan-out을 쓰지 않는다.** `Send`를 쓰면 한 superstep에 여러 노드 키가 올라오는데
`cli.py`의 스트림 루프는 `next(iter(update.items()))`로 첫 키만 읽고, 서브노드 이름에서
`STAGE_LABELS`·`STAGE_ORDER.index()`가 `KeyError`/`ValueError`로 죽는다. 노드 하나를
유지하면 CLI의 단계 배너 계약이 그대로 성립한다. `verify`에서 `Send`가 정말 필요해지면
그때 스트림 루프를 함께 고친다.

`create_agent`는 `checkpointer=False`로 컴파일한다 — 안 주면 바깥 그래프의
`SqliteSaver`(동기 전용)를 물려받는데 이 에이전트는 `astream`으로 돈다.

`recursion_limit`도 호출할 때마다 넘긴다 — `create_agent`는 그래프에 **9999**를
바인딩해두기 때문에, 안 넘기면 툴 루프가 사실상 무제한으로 돈다
(`SCOUT_SEARCH_RECURSION_LIMIT`, 기본 16).

**동기 LLM 호출은 `asyncio.to_thread`로 뺀다.** 후보 추출의 `invoke_structured`가 동기
`.invoke()`라 그냥 부르면 이벤트 루프를 막는다. 요소를 병렬로 돌리는데 여기서 루프가
멈추면 (1) 다른 요소가 사실상 순차 실행되고 (2) 그 요소의 웹검색 승인 결과가 루프로
돌아오지 못해 **사람이 답했는데 몇 초씩 반응이 없다**. `store` 접근은 루프 스레드에
남긴다 — sqlite 쓰기가 저절로 직렬화된다 ([CHANGELOG v18·v29](../CHANGELOG.md)).

**승인 프롬프트가 떠 있는 동안 진행 줄은 보류된다.** 병렬 요소가 계속 일하면서 화면에
줄을 밀어넣으면 질문이 위로 밀려 올라간다. 보류되는 것은 *출력*뿐이고 실행은 계속된다 —
장치와 근거는 [09-출력양식](../09-출력양식.md) "묻는 동안 진행 줄을 보류한다".
승인 문의 자체는 `SearchGate`의 락이 프롬프트 내내 잡혀 **한 번에 하나만** 뜬다.

**한도에 걸려도 그 요소가 죽지 않는다.** `ainvoke`는 `GraphRecursionError`에 상태를
담아주지 않아 모은 툴 기록이 함께 날아가고 후보가 0개가 된다. `agentkit.run_agent_loop`가
`astream`으로 마지막 상태를 들고 있어 **부분 기록으로 후보를 뽑고** 한도 초과를
`gaps`에 남긴다. `topup_dossier`가 kind별 필수 사실을 코드로 채우므로 탐색이 짧아도
dossier가 비지 않는다.

MCP 서버의 디스크 캐시(24h)가 있어서 재실행 시 HTTP는 대부분 캐시에서 나온다.

---

## 웹검색 사람 승인 (HITL)

외부 검색엔진에는 LLM이 만든 **자유 서술 질의**가 그대로 나간다 — 사내 프로젝트
맥락이 유출될 수 있다. 그래서 `web_search`만 사람 승인을 거친다. npm·PyPI·GitHub는
패키지명·저장소명만 나가는 레지스트리 조회라 승인 대상이 아니다.

```
  ? 인터넷 검색 "websocket server node 2026" — 허용할까요? [y/N]: n
  ? 거부 사유: 고유명사·제품명을 질의에 넣지 마세요
   → 거부 사유가 툴 결과로 에이전트에 돌아간다
   → 에이전트가 질의를 고쳐 재요청 → 다시 승인 프롬프트
```

**거부하면 원본 툴을 호출하지 않는다 — egress가 일어나지 않는다.** 승인 문구만 띄우고
요청이 나가버리면 이 기능은 장식이다. `test_search_approval.py`가 이 배선을 검사한다.

| 상황 | 동작 |
|---|---|
| 승인 | 원본 툴 호출, 예산 1 차감 |
| 거부 | egress 0. 거부 사유를 툴 결과로 반환 → 에이전트가 재질의 (예산 차감 없음) |
| 거부 3회 | 이후 웹검색 차단 — 무한 재질의 방지 |
| 예산 5회 소진 | 이후 프롬프트 없이 차단 |
| 비대화형 (파이프·CI) | 그 실행 내내 차단 + `gaps` 기록. `--auto-approve-search`로 열 수 있다 |

거부·차단은 전부 `gaps`에 남는다 — 근거가 없는 이유가 보고서에 드러나야 한다(불변식 12).

### 왜 `interrupt()`가 아닌가

LangGraph의 정석 HITL은 `interrupt()`다. 여기서는 `interview`가 이미 쓰는 **주입
콜러블** 패턴(`Approve` + `NonInteractive`)을 따른다. 이유 셋이다.

1. **파이프라인 전체가 async가 돼야 한다.** MCP 툴은 `func=None`인 async 전용이라
   에이전트를 `ainvoke`로 돌려야 하고, interrupt를 CLI까지 올리려면 바깥 그래프도
   `astream` + `AsyncSqliteSaver`가 된다 → `cli.py`·`graph.py`·`interview`의 실행
   모델까지 다시 짜야 한다
2. **`interrupt()`는 노드를 처음부터 재실행한다.** 거부→재질의 루프는 왕복마다
   재실행이 붙는다
3. **동시 interrupt가 여러 개면 id 맵 resume가 강제된다.** `create_agent`는 툴 콜마다
   별도 태스크라, 스칼라 `Command(resume=)`는 `RuntimeError`가 난다

**승인 콜러블이 나중에 `interrupt()`로 갈아끼울 이음매다** — 이 문서가 에이전트 자리를
미리 남겨뒀던 것과 같은 방식으로 남긴다.

---

## 출력

```sql
candidates (slug, component, name, kind, what_it_is)
facts      (slug, candidate, fact_id, label, value, url, retrieved_at)
gaps       (slug, candidate, note)
```

후보 8~10개, 후보당 사실 3~10개 → `facts` 30~80행 규모.

---

## 실패 처리

| 상황 | 동작 |
|---|---|
| MCP 툴 조회 실패 (404, 타임아웃) | 예외를 던지지 않고 `gaps`에 기록하고 계속 |
| GitHub 레이트리밋 (토큰 없음, 60req/h) | 위와 동일. 실행 초반에 경고 출력 |
| **에이전트 루프 자체가 실패** | 그 요소만 `gaps`에 기록하고 나머지 요소는 계속 (`gather(return_exceptions=True)`) |
| **웹검색 거부·차단** | `gaps`에 사유 기록. method 후보면 "웹검색 근거 없음"이 남는다 |
| 특정 요소의 후보 0개 | 그 요소는 `picks`에 "후보 없음"으로 남기고 계속 |
| 전체 후보 0개 | 조건 엣지로 조기 종료 |
| 후보 이름 중복 (요소 간) | dossier는 후보명 기준으로 캐시해 재사용 |

**파이프라인을 죽이지 않는다**는 게 원칙이다. 사실을 못 구한 것도 정보다.

---

## 절단 시

**절단선 1번** — `osv_query`를 뺀다. `osv.*` 사실이 사라지고 `risk` 근거가 줄지만
`npm.license`, `gh.archived`는 남는다. (**되돌렸다** —
[06-범위와일정](../06-범위와일정.md) 절단선 1번.)

**절단선 2번** — `method` kind 후보를 아예 만들지 않는다. `library`·`software`만 올린다.
후보 수가 8~10 → 6~8로 줄어 `verify` 시간도 함께 준다.

`web_search`는 **버리지 않는다** — `method` 후보의 유일한 근거이므로, 절단선 2번으로
`method`를 버리는 게 순서상 먼저다. 자세한 이유는 [06-범위와일정](../06-범위와일정.md).
