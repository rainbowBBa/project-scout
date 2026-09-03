# STEP 03 · analyze

> 개발에 필요한 요소를 도출하고 `necessity`·`priority`를 매긴다.
> 전부 저장하고 상위 3개만 다음 STEP으로 통과시킨다. LLM 1회. MCP 불필요.

**선행** STEP 02 · **시간** ~1h · **설계** [stages/1-design](../001_기술스택-조사-에이전트-설계/stages/1-design.md)

> **끝낸 작업의 기록이다.** 이 STEP이 만든 `analyze`는 STEP 09에서 `design`으로
> 대체됐다 — 설계 문서(`1-analyze.md`)도 `1-design.md`로 재작성됐다.
> 무엇이 왜 바뀌었는지는 [001 CHANGELOG v20](../001_기술스택-조사-에이전트-설계/CHANGELOG.md).

## 만들 것
- `scout/stages/analyze.py` (도메인 힌트 문자열 포함)
- `scout/graph.py` — `analyze` 노드 + 조건 엣지(요소 0개면 조기 종료)

## 완료 기준
- [x] `components` 6~10행이 생긴다 (걸러진 것까지 전부 저장)
- [x] `necessity`가 `unnecessary` 또는 `defer`인 요소가 **최소 1개** 있다
- [x] `necessity_reason`에 제약조건 숫자("200명", "3인 팀")가 인용된다
- [x] `kind` 5종 중 최소 3종이 등장한다 (배포·운영을 빠뜨리지 않는지)
- [x] `--max-components 3` 이 통과 요소를 3개로 제한한다
- [x] CLI에서 "[분석] 단계를 시작합니다." 뒤, "...종료합니다." 배너보다 먼저
  통과된 요소가 JSON이 아니라 `[necessity] name (kind) — priority N` +
  `이유: <necessity_reason>` 형태로 사람이 읽기 좋게 출력된다
  ([001/CHANGELOG v14](../001_기술스택-조사-에이전트-설계/CHANGELOG.md))

## 막히면
전부 `essential`로 나오면 프롬프트에 "더 단순한 대안이 있는지 먼저 검토하라"를 추가.
`refined_brief`에 범위 제외("이번엔 안 한다" 등)가 있는지 확인 — 걸러내기의 가장 강한
신호다.

**입력이 바뀜(2026-09-02)**: `interview`가 재설계되면서 `Interview.non_goals`·
`must_haves`·`scale` 같은 슬롯 필드가 사라졌다. `analyze`는 이제 `refined_brief`
프로즈 하나만 입력으로 받는다 — 판단 로직(범위 제외 → defer/unnecessary)은 그대로이고,
신호가 별도 필드에서 문장으로 옮겨갔을 뿐이다. 자세한 배경은
[001/CHANGELOG v13](../001_기술스택-조사-에이전트-설계/CHANGELOG.md)에 있다.

실제로 `uv run scout run "AI 요약 기능이 있는 팀 채팅 앱을 만들고 싶어. 메시지 전문검색이나
외부 공개는 이번엔 필요없어"`를 돌려 확인함: `components` 10행 생성, `kind` 5종
(feature/data/infrastructure/ops/integration) 전부 등장, `defer`(메시지 전문 검색)와
`unnecessary`(외부 서드파티 채널 연동) 각 1개, `necessity_reason`에 "200명"·"3인 팀"·
"3개월" 인용 확인. `select_passing_components()`는 별도 단위 검증으로
`--max-components` 값에 따라 상위 N개만 반환하고(필터 대상이 N개 미만이면 전부 반환),
빈 리스트에도 안전한 것을 확인함.
