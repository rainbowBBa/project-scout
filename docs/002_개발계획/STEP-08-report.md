# STEP 08 · report

> `scout.db`를 jinja2로 단일 HTML로 렌더링한다.
> 외부 CDN 없음, JS 0줄, 인라인 CSS. LLM 없음.

**선행** STEP 07 · **시간** ~1.25h · **설계** [stages/5-report](../001_기술스택-조사-에이전트-설계/stages/5-report.md)

## 만들 것
- `scout/templates/report.html.j2` — self-contained
- `scout/stages/report.py` — SQL 조회 + 렌더링
- `scout/cli.py` — 실행 끝 터미널 6줄 요약

## 완료 기준
- [ ] `report.html` 이 생성되고 브라우저에서 열린다
- [ ] **네트워크를 끊고 열어도 레이아웃이 깨지지 않는다** (CDN 의존 0의 증거)
- [ ] `overall`·`maturity`·`risk` 막대 3개가 그려지고, 숫자 없는 후보는 `근거 없음` 배지가 나온다
- [ ] `computed` / `judged` / `근거 없음` 배지 3종이 구분된다
- [ ] **`score_reason`이 막대 바로 아래** 붙는다 (떨어져 있으면 안 된다)
- [ ] 확정 스택 표에 `overall` 막대와 `margin=close` 시 `[근접]` 배지가 나온다
- [ ] `<details>` 섹션이 접히고 펴진다
- [ ] "지금 만들지 않아도 되는 것" 섹션에 `defer`/`unnecessary` 요소가 나온다
- [ ] "이번에 다루지 않은 요소"에 `--max-components`로 밀린 요소가 명시된다
- [ ] 빈 섹션이 사라지지 않고 "해당 없음 + 이유"로 표시된다

## 막히면
`jinja2`가 이미 깔려 있는지 `uv pip show jinja2` — langchain-core가 끌어올 수 있다.
종합 점수를 표시하려는 충동을 참는다 — 가중 합산이 없으니 그 숫자가 없다. `winner_reason`을 쓴다.
