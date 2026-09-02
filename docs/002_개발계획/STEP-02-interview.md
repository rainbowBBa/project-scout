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
- [ ] `uv run scout run "AI 요약이 있는 팀 채팅 앱"` 이 5개 질문을 되묻는다
- [ ] `runs` 행이 생기고 `refined_brief`가 **원문 복사가 아니다** (되묻기 답이 문장에 녹아 있다)
- [ ] `must_haves` `non_goals` `assumptions` 가 비어 있지 않다
- [ ] 빈 입력으로 답하면 기본값이 쓰이고 `assumptions`에 기록된다
- [ ] `scout show <slug> interview` 가 JSON을 출력한다

## 막히면
`with_structured_output` 파싱 실패 → `include_raw=True`로 원본 확인 후 스키마 축소.
`refined_brief`가 원문 복사로 나오면 프롬프트에 "답변 내용을 문장에 녹여라"를 명시.
