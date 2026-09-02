# 2 · search

← [단계 목록](README.md) · 이전: [1-analyze](1-analyze.md) · 다음: [3-verify](3-verify.md)

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

`components` 테이블에서 `necessity IN ('essential', 'valuable')`인 요소를
`priority` 순으로 정렬해 **상위 3개**만 (`--max-components`, 기본 3).
`defer`/`unnecessary`는 물론이고 우선순위가 밀린 요소도 이 단계에 들어오지 않는다 —
[1-analyze](1-analyze.md) 참조.

`interview` 제약조건도 함께 넣는다 — 질의 생성 방향을 잡는 데 쓴다.

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
| `gh.last_commit` `gh.archived` `gh.contributors` `gh.issue_close_rate` | `github_repo_health` |
| `osv.vulns` `osv.max_severity` | `osv_query` |
| `web.1` `web.2` `web.3` … | `web_search` (스니펫 순번) |

---

## kind별 dossier 수집 라우팅

| kind | 예 | 수집 경로 |
|---|---|---|
| `library` | socket.io, langchain | `npm_package`/`pypi_package` + `github_repo_health` + `osv_query` + `web_search` |
| `software` | PostgreSQL, Redis, Meilisearch | `github_repo_health` + `web_search` (+ 있으면 레지스트리) |
| `method` | 이벤트 소싱, CQRS, PG LISTEN/NOTIFY | `web_search`만 |

**`method`는 조회할 레지스트리가 없다.** 이건 결함이 아니라 사실이고, `dossier_gaps`에
명시적으로 드러나야 한다. judge가 "근거가 웹 스니펫 3건뿐"이라는 걸 알고 판단해야 한다.

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

## 동작 — 3턴 파이프라인 (에이전트 아님)

요소마다 아래를 돈다. LangGraph `Send`로 fan-out.

```
요소 "실시간 메시지 전달"

  (1) LLM   조사 질의 생성 (구조화)
            search_hints + 제약조건 → ["websocket server node",
                                       "socket.io alternative 2026",
                                       "postgres realtime push"]

  (2) 코드   npm_search + web_search 병렬 실행 (LLM 개입 없음)
            → 후보 추출 → kind 판정 → 위 라우팅대로 dossier 수집 병렬

  (3) LLM   후보 정리 · 중복 제거 (구조화)
            → 요소당 2~3개
```

### 왜 ReAct 에이전트가 아닌가

DuckDuckGo 스니펫 품질이 나쁘고 모델이 Sonnet이라, 에이전트에 검색을 맡기면 헤맨다.
질의를 만들고 결과를 정리하는 것만 LLM에 맡기고 **실행은 코드가 한다.**

예측 가능하고, 저렴하고, 어느 턴이 틀렸는지 짚힌다.
나중에 `create_react_agent`로 바꿀 여지는 남는다.

### 동시성

| 층 | 제한 |
|---|---|
| 요소 fan-out | LangGraph `Send`, 리듀스는 `Annotated[list, operator.add]` |
| LLM 호출 | `Semaphore(4)` |
| MCP 호출 | `Semaphore(8)` |
| MCP 서버 | 자체 토큰버킷 레이트리미터 (이중 방어) |

MCP 서버의 디스크 캐시(24h)가 있어서 재실행 시 HTTP는 대부분 캐시에서 나온다.
같은 후보가 여러 요소에 등장할 때도 이득을 본다.

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
| 특정 요소의 후보 0개 | 그 요소는 `picks`에 "후보 없음"으로 남기고 계속 |
| 전체 후보 0개 | 조건 엣지로 조기 종료 |
| 후보 이름 중복 (요소 간) | dossier는 후보명 기준으로 캐시해 재사용 |

**파이프라인을 죽이지 않는다**는 게 원칙이다. 사실을 못 구한 것도 정보다.

---

## 절단 시

**절단선 1번** — `osv_query`를 뺀다. `osv.*` 사실이 사라지고 `risk` 근거가 줄지만
`npm.license`, `gh.archived`는 남는다.

**절단선 2번** — `method` kind 후보를 아예 만들지 않는다. `library`·`software`만 올린다.
후보 수가 8~10 → 6~8로 줄어 `verify` 시간도 함께 준다.

`web_search`는 **버리지 않는다** — `method` 후보의 유일한 근거이므로, 절단선 2번으로
`method`를 버리는 게 순서상 먼저다. 자세한 이유는 [06-범위와일정](../06-범위와일정.md).
