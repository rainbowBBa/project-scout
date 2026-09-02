# STEP 02 · interview

> 대화형으로 되물어 막연한 요청을 구체화해 `refined_brief`를 만들고 `runs`에 저장한다.
> LLM 다중 턴 (질문 개수는 LLM이 판단). MCP 불필요.

**선행** STEP 01 · **시간** ~1h · **설계** [stages/0-interview](../001_기술스택-조사-에이전트-설계/stages/0-interview.md)

## 만들 것
- `scout/llm.py` — `ChatBedrockConverse` 팩토리 + 에러 체인
- `scout/graph.py` — `StateGraph` 골격 + `SqliteSaver` 체크포인터
- `scout/stages/interview.py` — 대화 루프는 내부 LangGraph 서브그래프
  (`ask_question → get_answer → (반복) → synthesize`)로 구현
- `scout/cli.py` — `run` 서브커맨드 (+`--from` `--stop-after` `--max-components` `--max-candidates`),
  서브커맨드 없이 `uv run scout`만 실행해도 같은 파이프라인이 도는 기본 진입점
  ([001/CHANGELOG v14](../001_기술스택-조사-에이전트-설계/CHANGELOG.md))

## 완료 기준
- [x] `uv run scout run "AI 요약이 있는 팀 채팅 앱"`이 대화형으로 되묻는다 —
  질문 개수는 고정 5개가 아니라 LLM이 매 턴 판단해 가변적으로 묻는다
- [x] raw_description에 이미 있는 정보는 다시 묻지 않는다 (이전에는 "구현하지 않음"으로
  남겨뒀던 항목 — 이번 재설계로 해결)
- [x] `runs` 행이 생기고 `refined_brief`가 **원문 복사가 아니다** (대화 내용이 문장에
  녹아 있고, 대화에서 나온 규모·예산·팀·데드라인 등 구체적인 내용을 담고 있다)
- [x] 빈 입력으로 답하거나 비대화형(파이프·CI)으로 실행하면 `assumptions`에 기록된다
- [x] `scout show <slug> interview`가 JSON을 출력한다 (`raw_description` ·
  `refined_brief` · `assumptions` 세 필드)
- [ ] `uv run scout`를 서브커맨드 없이 실행하면 "프로젝트 설명 입력: "으로
  대화형으로 설명을 받고, "[인터뷰] 단계를 시작합니다."/"...종료합니다." 배너
  사이에서 대화가 진행된다

## 막히면
질문 생성(`ask_question`) 구조화 출력 파싱 실패 → 1회 재시도, 그래도 실패하면 대화를
그냥 끝낸다(질문 하나 못 만드는 게 파이프라인을 막으면 안 된다).
최종 합성(`synthesize`) 파싱 실패 → `include_raw=True`로 원본 확인 후 스키마 축소.
`refined_brief`가 원문 복사로 나오면 프롬프트에 "대화 내용을 문장에 녹여라"를 명시.

## 재설계 기록 (2026-09-02)

최초 구현은 고정 5문항 + `Interview`에 슬롯 필드 8개(`scale`·`budget_monthly_usd`·
`team_size`·`team_languages`·`deadline_months`·`data_sensitivity`·`must_haves`·
`non_goals`)였다. 사용자 요청으로 두 가지를 바꿨다 — 자세한 배경과 이유는
[001/CHANGELOG v13](../001_기술스택-조사-에이전트-설계/CHANGELOG.md)에 있다.

1. **대화형 다중 턴**으로 전환. 질문 개수·내용을 LLM이 매 턴 판단하고, 이 루프를
   `stages/interview.py` 안의 LangGraph 서브그래프로 구현했다.
2. **슬롯 필드 8개를 전부 제거**하고 `Interview`를 `raw_description` · `refined_brief` ·
   `assumptions` 세 필드로 단순화했다. 슬롯이 담던 정보는 `refined_brief` 프로즈 안에
   자연어로 들어간다.

이전에 겪었던 `budget_monthly_usd`에 JSON `null` 대신 문자열 `"null"`을 쓰는 버그와
그 보정 코드(`_recover_from_tool_call`)는 해당 필드 자체가 없어지면서 함께 사라졌다.
