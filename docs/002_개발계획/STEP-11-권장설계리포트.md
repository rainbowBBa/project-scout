# STEP 11 · 권장 설계 리포트

> 보고서 최상단을 "권장 설계(확정본)"로 바꾼다. 섹션 2개를 신설하고,
> 기본틀(v1)을 나란히 둔 **v1↔v2 대조**를 넣는다.
> **LLM은 여전히 쓰지 않는다** — `evaluate`가 쓴 문장을 렌더링만 한다.

**선행** STEP 10 · **시간** ~1h · **설계** [stages/5-report](../001_기술스택-조사-에이전트-설계/stages/5-report.md) "화면 구조"

## 만들 것

- `scout/stages/report.py` — `build_report_context`에
  `store.get_design(slug)` · `store.get_final_design(slug)` 추가,
  `needs_comparison=false` 그룹 분리
- `scout/templates/report.html.j2` — 섹션 2개 신설 + 순서 변경
- `tests/test_report.py` — 새 섹션 검증 추가

## 섹션 순서

| # | 섹션 | 출처 | 상태 |
|---|---|---|---|
| 1 | **권장 설계 (확정본)** | `final_designs` | 신설 · 최상단 |
| 2 | **설계 개요 — v1 대조** (`<details>`) | `designs` | 신설 |
| 3 | 확정 스택 | `picks` + `scores` | 기존 |
| 4 | **설계에서 이미 정해진 부분** | `components` (`needs_comparison=false`) | 신설 |
| 5 | 지금 만들지 않아도 되는 것 | `components` (`defer`/`unnecessary`) | 기존 |
| 6 | 이번에 다루지 않은 요소 | `components` | 기존 |
| 7~10 | 다음 명령어 · 요소별 비교 · 탈락 사유 · 근거 목록 | 기존 | 기존 |

1번 섹션 내부 순서:

```
summary                 확정된 설계 한 단락
shape · data_flow       ★ 확정된 구조와 흐름 — "수정 설계"의 본문
설계가 어떻게 바뀌었나    ★ changes_from_design
build_order · integration_notes · combination_risks · unresolved
```

`build_report_context`의 조립 로직은 **그대로 둔다** — SQL 조인·그룹핑만 하고
`verify`·`evaluate`가 끝낸 판단을 다시 해석하지 않는다. **대조는 같은 이름의 필드를
나란히 놓는 것**이고, 차이를 문장으로 쓰는 건 `evaluate`의 `changes_from_design`이
이미 했다.

## 완료 기준

- [ ] `report.html` 최상단이 **권장 설계**이고, 문장에 고른 후보 이름이 보인다
- [ ] **확정 `shape`·`data_flow`가 최상단에 렌더링된다** — 이게 "수정 설계"의 본문이다
- [ ] **"설계가 어떻게 바뀌었나"** 블록이 `changes_from_design`을 보여준다
- [ ] `changes_from_design`이 비면 **섹션이 사라지지 않고** "조사 결과가 기본틀을
      바꾸지 않았다"가 표시된다 (불변식 12)
- [ ] `integration_notes` · `combination_risks` · `build_order` · `unresolved` 가
      각각 렌더링된다 (하나라도 빠지면 실패)
- [ ] `final_designs` 행이 **없을 때 섹션이 사라지지 않는다** —
      "설계 확정 실패 + `gaps`의 이유"가 같은 자리에 찍힌다 (불변식 12)
- [ ] "설계 개요"가 `<details>`로 접혀 있고, 펴면 **v1의 같은 필드**(`shape` ·
      `data_flow`)와 `open_questions`가 나온다 — 확정본과 나란히 읽힌다
- [ ] `open_questions`가 비어 있으면 "해당 없음 + 이유"가 나온다
- [ ] "설계에서 이미 정해진 부분"에 `needs_comparison=false` 요소가
      `no_comparison_reason`과 함께 나온다
- [ ] 그 요소들이 "지금 만들지 않아도 되는 것"에 **중복으로 나오지 않는다** —
      두 섹션의 의미가 다르다 (필요 없는 것 / 이미 정해진 것)
- [ ] **네트워크를 끊고 열어도 레이아웃이 깨지지 않는다** (CDN 의존 0 유지)
- [ ] `uv run pytest tests/test_report.py` 통과 — 시드 데이터로 위 항목을 검증한다
- [ ] `report.py`에 LLM 호출이 0건이다 (`grep -n "llm\|invoke" stages/report.py`)

## 막히면

**요약 문장을 만들고 싶어지면 멈춘다.** 필요한 문장은 이미 있다 —
`final_designs.summary` · `stack_rationale` · `winner_reason` · `solves_reason`.
`report`에서 문장을 생성하면 불변식 7이 깨지고, 그 순간부터 보고서 문체 튜닝에
시간이 사라진다.

**섹션 4와 5를 한 섹션으로 합치려는 충동을 참는다.** "조사하지 않았다"는 결과는 같지만
이유가 다르다 — 하나는 **필요 없어서**, 하나는 **이미 정해져서**다. 합치면 사용자가
설계의 전제를 못 본다.

**v1과 v2의 차이를 코드가 계산하려는 충동을 참는다.** diff를 떠서 하이라이트하고
싶어지지만, 산문 두 개의 의미 있는 차이는 문자열 비교로 안 나온다. 무엇이 왜 바뀌었는지는
`evaluate`가 `changes_from_design`에 이미 썼다 — **템플릿은 두 값을 나란히 놓고 그
목록을 함께 보여주면 된다.** 여기서 차이를 만들어내면 불변식 7이 깨진다.

**긴 산문의 줄바꿈** — `Architecture.shape`·`data_flow`는 여러 줄짜리 문자열이다.
`<pre>` 또는 `white-space: pre-wrap`으로 감싸지 않으면 한 줄로 뭉친다.
`autoescape=True`는 유지한다.
