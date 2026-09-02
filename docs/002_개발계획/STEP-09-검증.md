# STEP 09 · 검증

> 테스트 4종을 마무리하고 E2E를 1회 완주한다.
> 각 테스트는 커버리지가 아니라 **설계의 특정 주장**을 검증한다.

**선행** STEP 08 · **시간** ~1h · **설계** [07-검증](../001_기술스택-조사-에이전트-설계/07-검증.md)

## 만들 것
- `tests/test_stale_regression.py` — 아카이브 패키지가 최종 순위에서 탈락하는지
- `tests/test_necessity_wiring.py` — 걸러낸 요소가 `search`에 안 들어가고 보고서에 나타나는지
- (`test_egress.py`는 STEP 04, `test_grounding.py`는 STEP 06에서 이미 만듦)

## 완료 기준
- [ ] **E2E 완주** — `scout run "AI 요약이 있는 팀 채팅 앱, 3인 팀, TypeScript 숙련, 월 $200, 3개월"` 이 크래시 없이 `report.html`까지 간다
- [ ] `uv run pytest` **4종** 전부 통과
- [ ] `test_necessity_wiring.py` — `defer`/`unnecessary` 요소가 `search` 입력에 없고, 보고서 "지금 만들지 않아도 되는 것"에 렌더링되고, 걸러진 게 0개면 경고가 뜬다
- [ ] `uv run ruff check` 가 `scout/`의 httpx import를 `TID251`로 잡는다 (grep 안 함)
- [ ] `uv sync --package scout-net-mcp` 가 langchain 없이 성공한다
- [ ] `analyze`가 최소 1개를 걸러냈다 · `winner_reason`에 제약조건이 인용됐다
- [ ] `usage_metadata`로 실제 토큰을 집계해 001의 추정(입력 100~150k)과 비교했다

## 막히면
`test_stale_regression`이 실패하면 두 경로 중 어디가 끊겼는지 본다 —
judge의 `solves_it` 또는 `evaluate`의 `maturity` 계산. 둘 중 하나만 작동해도 통과해야 한다.
`test_necessity_wiring`은 LLM을 안 부른다 — 고정 픽스처로 코드 경로만 본다.
