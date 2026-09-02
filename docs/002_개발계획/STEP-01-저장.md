# STEP 01 · 저장

> Pydantic 스키마 전체와 sqlite3 DDL·CRUD를 만든다.
> 뒤의 모든 STEP이 이 계약 위에 올라간다. (`config.py`는 STEP 00에서 이미 만들었다)

**선행** STEP 00 · **시간** ~1h · **설계** [03-저장](../001_기술스택-조사-에이전트-설계/03-저장.md)

## 만들 것
- `scout/schemas.py` — `Interview` `Component` `Candidate` `Fact` `Verdict` `ElementPick`
- `scout/store.py` — DDL 8개 테이블 + upsert/select 함수 (ORM 없음)
- `scout/state.py` — `ScoutState` (TypedDict)
- `scout/cli.py` — `show` 서브커맨드 추가

## 완료 기준
- [x] `scout.db` 에 8개 테이블(`runs` `components` `candidates` `facts` `gaps` `verdicts` `citations` `scores` `picks`)이 생성된다
- [x] grounding 검증 SQL(`citations LEFT JOIN facts`)이 손으로 넣은 데이터에서 동작한다
- [x] `scout show <slug> interview` 가 빈 테이블에도 크래시 없이 응답한다

## 막히면
`ty`가 Pydantic 모델에 오탐을 쏟으면 그날 바로 끈다. 프리뷰 도구와 씨름하지 않는다.

`03-저장.md`의 DDL 스케치와 각 단계 문서의 스키마가 어긋난 지점 2건(`components.priority`,
`verdicts.unsupported_claims_json` 누락)을 구현 중 발견해 문서를 고쳤다 — `001/CHANGELOG.md` v12.
`store.py`의 CRUD 함수는 `conn`을 노출하지 않고 `slug` 기준으로 자체 연결을 열고 닫는다
(CLAUDE.md의 `store.upsert_facts(slug, candidate, facts)` 패턴을 따름) —
`runs_dir` 키워드 인자로 테스트에서 임시 디렉터리를 주입할 수 있다.
