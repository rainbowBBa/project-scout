# STEP 02 · interview

> 되묻기로 막연한 요청을 구체화해 `refined_brief`를 만들고 `runs`에 저장한다.
> LLM 1회. MCP 불필요.

**선행** STEP 01 · **시간** ~1h · **설계** [stages/0-interview](../001_기술스택-조사-에이전트-설계/stages/0-interview.md)

## 만들 것
- `scout/llm.py` — `ChatBedrockConverse` 팩토리 + 에러 체인
- `scout/graph.py` — `StateGraph` 골격 + `SqliteSaver` 체크포인터
- `scout/stages/interview.py`
- `scout/cli.py` — `run` 서브커맨드 (+`--from` `--stop-after` `--max-components` `--max-candidates`)

## 완료 기준
- [x] `uv run scout run "AI 요약이 있는 팀 채팅 앱"` 이 5개 질문을 되묻는다
- [x] `runs` 행이 생기고 `refined_brief`가 **원문 복사가 아니다** (되묻기 답이 문장에 녹아 있다)
- [x] `must_haves` `non_goals` `assumptions` 가 비어 있지 않다
- [x] 빈 입력으로 답하면 기본값이 쓰이고 `assumptions`에 기록된다
- [x] `scout show <slug> interview` 가 JSON을 출력한다

## 막히면
`with_structured_output` 파싱 실패 → `include_raw=True`로 원본 확인 후 스키마 축소.
`refined_brief`가 원문 복사로 나오면 프롬프트에 "답변 내용을 문장에 녹여라"를 명시.

구현 중 관찰한 것 두 가지:

- **`budget_monthly_usd`에 JSON `null` 대신 문자열 `"null"`을 쓰는 버그**를 실제로 겪었다.
  `int | None` 필드를 tool-calling 스키마로 강제하면 모델이 "모른다"를 문자열로 표현하려는
  경향이 있다 — 프롬프트에 "0을 쓰지 마라" 반례를 박아도 재발했다. `interview.py`의
  `_recover_from_tool_call`이 `raw.tool_calls`에서 이 특정 오탈을 보정해 재검증한다.
- **"설명에 이미 답이 있으면 질문을 건너뛴다"는 구현하지 않았다.** `LLM 1회` 제약상 되묻기
  전에 LLM을 한 번 더 태우지 않고는 판단할 수 없어서, 5개 질문은 항상 다 묻는다. 빈 입력
  기본값은 raw_description을 보지 않고 정해지므로, 설명에 이미 답이 있는데 사용자가 Enter만
  치면 `assumptions`에 부정확한 "미응답" 기록이 남을 수 있다 — `refined_brief`·`must_haves`
  등 나머지 필드는 LLM이 raw_description을 함께 보고 채우므로 값 자체는 영향받지 않는다.
