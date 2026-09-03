# STEP 07 · evaluate

> `maturity`·`risk`를 코드가 계산하고, judge가 종합 점수(`overall`)와 이유를 낸다.
> 가중 합산은 없다. LLM은 요소당 1회.

**선행** STEP 06 · **시간** ~1h · **설계** [stages/4-evaluate](../001_기술스택-조사-에이전트-설계/stages/4-evaluate.md)

## 만들 것
- `scout/rubric.py` — `maturity`/`risk` 점수 공식 (가중치 로직 없음)
- `scout/stages/evaluate.py` — 탈락 처리 + 점수 계산 + `ElementPick`
- `scout/prompts.py` — `EVALUATE_*` (반례 4개를 프롬프트에 박는다)
- `scout/graph.py` · `scout/cli.py` — 노드 연결 + `show <slug> evaluate`
- **`scout_net_mcp/providers/github.py` + `scout/stages/search.py` — `gh.contributors`**
  STEP 04에서 빠진 사실이다. `maturity` 세 신호 중 버스 팩터를 보는 건 이것뿐이라
  (릴리스 최근성·커밋 활성은 둘 다 "최근성"이다) 여기서 채우고 간다

## 완료 기준
- [ ] `scores` 에 `maturity`·`risk`(`computed`) + `overall`(`judged`) 3기준이 들어간다
- [ ] 숫자가 없는 후보는 `score=NULL`, `source="unavailable"` (0이 아니다)
- [ ] `maturity`가 세 신호의 **최소값**을 취한다 (평균이 아니다)
- [ ] **`overall`이 `maturity`·`risk`의 평균이 아니다** — `maturity=5`인데 요구 미충족 케이스에서 `overall`이 4 이상 나오면 프롬프트 실패
- [ ] 후보마다 `score_reason`에 `fact_id` 또는 verdict가 인용된다
- [ ] `picks` 에 `winner` `winner_reason` `runner_up_note` `margin` 이 채워진다
- [ ] `winner_reason`에 **제약 인용 + 2위와의 점수 차이** 둘 다 들어간다
- [ ] `margin`이 `overall` 차이로 `decisive`/`close`를 낸다
- [ ] 통과 후보가 1개면 LLM을 부르지 않고 그대로 1위
- [ ] `gh.contributors`가 dossier에 들어오고 `maturity`가 그 값을 쓴다
- [ ] 신호가 일부만 있으면 **있는 신호만의 최소값** — 없는 신호를 5나 1로 채우지 않는다
- [ ] `osv.*`가 없으면 취약점 항목을 건너뛴다 (0건으로 간주해 5를 주지 않는다)
- [ ] 탈락 후보도 `maturity`·`risk`가 `scores`에 남는다 (이중 안전망의 증거)

## 막히면
`winner`가 `ranking[0]`과 불일치하면 구조 검증에서 잡고 1회 재시도.
아카이브 패키지가 탈락하지 않으면 `maturity` 공식의 `archived` 분기를 확인.
