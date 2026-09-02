# STEP 06 · verify

> 후보를 하나씩 독립 판정한다(pointwise). judge는 dossier의 `fact_id`만 인용하고,
> 코드가 SQL로 그 인용을 대조한다. **이 프로젝트의 중심 STEP.**

**선행** STEP 05 · **시간** ~1.25h · **설계** [stages/3-verify](../001_기술스택-조사-에이전트-설계/stages/3-verify.md)

## 만들 것
- `scout/stages/verify.py` — judge 프롬프트 + 앵커 루브릭
- `scout/grounding.py` — `citations LEFT JOIN facts` 검증 (LLM 없음)
- `scout/graph.py` — `Send` fan-out (후보별)
- `tests/test_grounding.py`

## 완료 기준
- [ ] `verdicts` 8~10행 + `citations` 가 채워진다
- [ ] **`test_grounding.py` 통과** — dossier에 없는 id를 인용한 `Verdict`를 주입하면 잡히고 `confidence`가 강등된다
- [ ] 아카이브 패키지를 주입하면 `solves_it=false`가 나오고 이유에 릴리스 사실이 인용된다
- [ ] `citations`가 빈 판정은 `confidence`가 강등된다
- [ ] `gaps`가 많은 `method` 후보는 `confidence: low`가 나온다

## 막히면
judge가 거의 전부 `solves_it=true`를 주면 앵커 루브릭이 약한 것 — false 조건을 더 구체적으로.
`Verdict`는 필드가 많아 파싱 실패가 가장 잦다. `include_raw=True`로 원본을 잡는다.
