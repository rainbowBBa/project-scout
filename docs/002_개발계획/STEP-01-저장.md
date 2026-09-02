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
- [ ] `scout.db` 에 8개 테이블(`runs` `components` `candidates` `facts` `gaps` `verdicts` `citations` `scores` `picks`)이 생성된다
- [ ] grounding 검증 SQL(`citations LEFT JOIN facts`)이 손으로 넣은 데이터에서 동작한다
- [ ] `scout show <slug> interview` 가 빈 테이블에도 크래시 없이 응답한다

## 막히면
`ty`가 Pydantic 모델에 오탐을 쏟으면 그날 바로 끈다. 프리뷰 도구와 씨름하지 않는다.
