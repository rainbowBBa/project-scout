# STEP 12 · 검증

> 테스트 6종을 마무리하고 E2E를 1회 완주한다.
> 각 테스트는 커버리지가 아니라 **설계의 특정 주장**을 검증한다.

**선행** STEP 11 · **시간** ~1.5h · **설계** [07-검증](../001_기술스택-조사-에이전트-설계/07-검증.md)

## 만들 것

- `tests/test_stale_regression.py` — 아카이브 패키지가 최종 순위에서 탈락하는지
- `tests/test_necessity_wiring.py` — 걸러낸 결정 지점이 `search`에 안 들어가고
  보고서에 나타나는지. **축이 셋이다**
  (`necessity` · `needs_comparison` · `alternatives`)
- `tests/test_design_no_facts.py` — `design`의 툴 결과가 dossier를 오염시키지 않는지
- (`test_egress.py` STEP 04 · `test_grounding.py` STEP 06 ·
  `test_search_approval.py` STEP 05 · `test_report.py` STEP 08·11에서 이미 만듦)

세 개 다 LLM을 부르지 않는다 — 고정 픽스처로 코드 경로만 본다.

## 완료 기준

### 자동

- [x] `uv run pytest` **6종 + `test_report`** 전부 통과 — 94개 통과
- [x] `test_necessity_wiring.py` — 통과 필터가 **세 축**이다
  ```
  1. defer/unnecessary 가 search 입력 목록에 없다
  2. needs_comparison=false 도 search 입력 목록에 없다
  3. alternatives 가 2개 미만인 것도 없다 (고를 것이 없으면 결정 지점이 아니다)
  4. 1번이 보고서 "지금 만들지 않아도 되는 것"에 렌더링된다
  5. 2·3번이 보고서 "설계에서 이미 정해진 부분"에 렌더링된다
  6. 걸러진 것이 0개면 경고가 출력된다
  ```
  → 3번은 `tests/test_decision_points.py`가 먼저 검사한다 (v26). **흡수하지 않고
    축만 확인**했다 — 세부(코드가 내리는 경로·왕복·미커버 보기)는 그쪽에 그대로 둔다.
    여기에는 축 셋이 **각각 혼자서도 막는지**와 priority 컷이 걸러내기보다 **뒤에**
    오는지를 넣었다. `search_node`가 `state["components"]`만 본다는 소비자 쪽 배선도
    함께 본다 — 여기서 DB를 다시 읽으면 걸러내기가 예산을 하나도 아끼지 못한다
- [x] `test_design_no_facts.py` — 세 가지를 본다
  ```
  1. design 이 툴을 불러도 facts 테이블에 행이 생기지 않는다
  2. design 이 부른 npm_package 의 값이 candidates/facts 어디에도 없다
  3. 통과 결정 지점의 search_hints 가 비면 gaps 에 기록된다
  ```
  → 툴 대역이 **실제로 호출되는** 실행에서 본다. 툴을 안 부르면 "facts가 비었다"가
    아무것도 증명하지 않으므로, 같은 payload가 **설계 추출 프롬프트에는 들어가고**
    dossier에는 안 들어가는 것을 함께 확인한다
- [x] `test_stale_regression.py` — 아카이브 후보가 탈락하고, 탈락 이유에
      "마지막 릴리스" 사실이 인용된다
  → 이중 안전망(불변식 5)을 **두 경로로 나눠** 본다. 한 시나리오에서 같이 보면 어느
    쪽이 일했는지 알 수 없어 한쪽이 죽어도 통과한다. 계산 경로는 `rubric.maturity`,
    판정 경로는 judge의 `solves_it`, 그리고 **judge가 낡은 사실을 무시했을 때**
    `normalize`의 동점 정렬이 순위를 뒤집는지를 각각 본다
- [x] `uv run ruff check` 가 `scout/`의 httpx import를 `TID251`로 잡는다 (grep 안 함)
      — `scout/`에 임시 파일을 넣어 실측: `httpx`·`requests`·`urllib.request` 3건 검출
- [x] `uv sync --package scout-net-mcp` 가 langchain 없이 성공한다
      — 설치 후 `uv pip list`에 `scout-net-mcp` 하나뿐 (langchain·langgraph·boto3 없음)

### E2E — 새 slug로 1회

```bash
uv run scout run "AI 요약이 있는 팀 채팅 앱, 사내 200명, 3인 TypeScript 팀, 월 $200, 3개월"
```

- [ ] 크래시 없이 `report.html`까지 간다
- [ ] `scout.db` **10개 테이블**이 모두 채워진다 (`designs` · `final_designs` 포함)
- [ ] 승인 프롬프트가 `design` 3회 + `search` (요소×최대 5회) 안에서 끝난다
- [ ] 거부 루프 육안 확인 — `n` + 사유를 주면 **에이전트가 사유를 반영해 질의를 바꿔서**
      다시 물어본다. 같은 질의를 그대로 다시 물으면 사유가 전달되지 않은 것이다
- [ ] `usage_metadata`로 실제 토큰을 집계해 001의 추정과 비교한다.
      **`SCOUT_LLM_CACHE`를 끄고 측정한다** — 적중한 호출은 집계에서 빠진다
      (`design`이 에이전트가 되고 확정 1회가 늘었으므로 **입력이 늘어난다** — 얼마나
      늘었는지를 기록한다)

### 판단 품질 — 육안 확인 (테스트가 못 잡는 것)

- [ ] **`search_hints`가 영어 기술 어휘다** — 요소 이름 복사가 아니다.
      이번 재설계의 직접 확인이다
- [ ] `needs_comparison=false`가 최소 1개이고 그 판단이 **실제로 맞다**
- [ ] `necessity`의 `defer`/`unnecessary`가 최소 1개이고 그 판단이 실제로 맞다.
      `necessity_reason`에 "200명"·"3인 팀" 같은 숫자가 인용된다
- [ ] `winner_reason`에 제약조건과 2위와의 점수 차이가 들어 있다
- [ ] **`final_designs.summary`가 조립을 말한다** — 고른 후보 이름이 들어 있고,
      `combination_risks`가 `cons`의 사본이 아니다
- [ ] `report.html`을 브라우저에서 열어 막대·`<details>`·배지가 정상이고,
      네트워크를 끊어도 깨지지 않는다

## 막히면

`test_stale_regression`이 실패하면 두 경로 중 어디가 끊겼는지 본다 —
judge의 `solves_it` 또는 `evaluate`의 `maturity` 계산. 둘 중 하나만 작동해도 통과해야 한다.

`test_design_no_facts`가 실패하면 `design.py`가 `store.upsert_facts`를 부르고 있는지
본다. 편의로 넣고 싶어지는 자리라 실수가 나기 쉽다 —
[stages/1-design.md](../001_기술스택-조사-에이전트-설계/stages/1-design.md)
"이 단계의 툴 결과는 사실이 아니다"를 다시 읽는다.

E2E에서 기존 run 폴더를 재사용하면 `no such column`이 난다. **새 slug로 돌린다** —
`components` 컬럼이 STEP 09에서 바뀌었고 마이그레이션 장치가 없다.

토큰이 추정을 크게 넘으면 `design`의 `recursion_limit`(10)과 웹검색 예산(3)을 먼저 본다.
설계 에이전트가 툴 루프를 오래 도는 게 가장 흔한 원인이다.
`gaps`에 "툴 탐색이 한도에 걸려 중단됨"이 매번 찍히면 10이 너무 빡빡한 것이다 —
설계 품질을 보고 올린다.
