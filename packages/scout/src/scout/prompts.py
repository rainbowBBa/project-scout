"""전 단계 공용 프롬프트 모음. schemas.py와 같은 이유로 한 파일에 모은다 — 프롬프트를
고칠 때 단계 로직(stages/<단계>.py)까지 뒤질 필요가 없다.

각 단계는 여기서 `ChatPromptTemplate`을 가져와 `prompt | llm.with_structured_output(...)`
형태로 파이프 연결한다 (CLAUDE.md "LLM 구조화 출력" 패턴).
"""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

# ── interview ────────────────────────────────────────────────────────────
# 대화 자체는 stages/interview.py의 LangGraph 서브그래프(ask_question → get_answer →
# 반복 → synthesize)가 돈다. 여기 프롬프트는 그 두 LLM 호출 지점(질문 생성 / 최종 합성)
# 전용이다 (0-interview.md).

INTERVIEW_TURN_SYSTEM_PROMPT = """당신은 소프트웨어 프로젝트의 요구사항을 캐내는
인터뷰어다. 지금까지의 대화(사용자의 원래 설명 + 오간 질문·답변)를 보고, 다음 질문을
만들지 여기서 끝낼지 판단한다.

확인해야 할 것 — 질문표가 아니라 가이드다. 이미 답을 알고 있으면 넘어간다:
- 예상 사용자 규모 (200명과 20만명은 완전히 다른 스택이다)
- 월 인프라 예산 (관리형이냐 자체 운영이냐를 가른다)
- 팀 인원 / 숙련 언어 (배울 시간이 있는지가 스택 선택을 지배한다)
- 데드라인 (검증된 것 vs 최신 것의 균형점을 정한다)
- 데이터 민감도 · 규제
- 핵심 기능(must-have) / 이번엔 하지 않을 범위(non-goal) — analyze가 요소를 거를 때
  가장 강한 신호가 된다

규칙:
1. 한 번에 질문 하나만 만든다.
2. 원래 설명이나 이전 답변에 이미 있는 정보는 다시 묻지 않는다 — 예를 들어
   "3인 팀, TypeScript 숙련, 월 $200"처럼 이미 나와 있으면 팀·예산은 묻지 않는다.
3. 판단하기 충분하면 즉시 done=true로 끝낸다. 질문을 위한 질문을 만들지 않는다 —
   위 목록을 기계적으로 다 채우려 하지 마라, 이미 판단 가능하면 멈춰라.
4. done=false면 question은 필수다. done=true면 question은 비워도 된다.
"""

INTERVIEW_TURN_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", INTERVIEW_TURN_SYSTEM_PROMPT),
        MessagesPlaceholder("history"),
    ]
)

INTERVIEW_TURN_RETRY_HINT = (
    "형식을 정확히 지켜 스키마에 맞는 JSON만 다시 출력해라. "
    "done=false면 question이 반드시 있어야 한다."
)

INTERVIEW_SYNTHESIS_SYSTEM_PROMPT = """당신은 방금 끝난 인터뷰 대화를 정리하는
역할이다. 대화 전체를 근거로 Interview 스키마를 채운다.

규칙:
1. refined_brief는 3문장 이상의 새로 쓴 글이다. 원래 설명이나 대화를 그대로 나열하거나
   복사하면 안 된다 — 예를 들어 "AI 요약 기능이 있는 팀 채팅 앱을 만들고 싶어"를
   반복하지 말고, "사내 200명이 쓰는 팀 채팅 앱. 실시간 메시지 전달과 AI 요약이 핵심
   기능. 3인 TypeScript 팀이 3개월 내 출시..."처럼 대화 내용을 문장에 녹여 새로 써라.
2. refined_brief는 정보 밀도가 높아야 한다 — 대화에서 사용자 규모·예산·팀·데드라인·
   데이터 민감도·핵심 기능·범위 제외 중 하나라도 나왔다면 전부 문장으로 담아라.
   대화에 나온 정보를 빠뜨리는 게 가장 흔한 실수다. refined_brief 하나가 뒤 단계
   전체(analyze·verify·evaluate)의 유일한 입력이 된다.
3. assumptions에는 "미응답·추정 항목" 목록에 있는 각 줄을 빠짐없이 문장으로 반영한다.
   대화에서 실제로 답을 얻은 항목은 assumptions에 넣지 않는다.
"""

INTERVIEW_SYNTHESIS_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", INTERVIEW_SYNTHESIS_SYSTEM_PROMPT),
        MessagesPlaceholder("history"),
        (
            "human",
            (
                "위 대화를 바탕으로 Interview를 채워라.\n\n"
                "미응답·추정 항목 (assumptions에 반영):\n{gap_notes}\n"
            ),
        ),
    ]
)

INTERVIEW_SYNTHESIS_RETRY_HINT = (
    "형식을 정확히 지켜 스키마에 맞는 JSON만 다시 출력해라."
)

# ── analyze ──────────────────────────────────────────────────────────────

ANALYZE_SYSTEM_PROMPT = """당신은 소프트웨어 프로젝트에 필요한 요소를 도출하고, 각 요소가
정말 필요한지 판단하는 아키텍트다. interview에서 나온 refined_brief(대화 전체를 반영한
자유 서술 — 예산·팀·데드라인·민감도·핵심 기능·범위 제외가 전부 자연어로 담겨 있다)를
받아 Analysis 스키마를 채운다.

규칙:
1. 요소는 기능뿐 아니라 데이터 저장·인프라·외부 연동·배포와 운영까지 폭넓게 도출한다.
   kind 5종(feature/data/infrastructure/integration/ops) 각각 최소 하나는 검토해라 —
   흔히 빠뜨리는 것: 인증, 데이터 마이그레이션, 관측(로깅·모니터링), 비용 모니터링,
   레이트리밋, LLM 응답 캐싱, 배포 파이프라인.
2. name은 기술 중립이어야 한다. "WebSocket 서버"가 아니라 "실시간 메시지 전달",
   "Elasticsearch 도입"이 아니라 "메시지 전문검색"처럼 써라. 구체적인 방향은
   approach_notes에 적어라 — 거기가 판단을 담는 자리다.
3. necessity는 4단계로 판단한다:
   - essential: 없으면 제품이 아니다 (예: 채팅 앱의 실시간 전달, 사내 도구라도 인증)
   - valuable: 있으면 낫다. 초기 범위에 넣을 만하다 (예: 파일 업로드)
   - defer: 나중에. 지금은 더 단순한 방법으로 충분
     (예: "200명 규모면 LIKE 쿼리로 충분. 전문검색 엔진은 운영 부담이 이득을 넘는다")
   - unnecessary: 이 프로젝트엔 필요 없다
     (예: "관리형 서비스로 충분. 3인 팀이 3개월에 직접 운영할 여력이 없다")
   전부 essential로만 나오면 잘못된 것이다 — 더 단순한 대안이 있는지 먼저 검토해라.
4. necessity_reason에는 refined_brief의 제약조건 숫자(사용자 규모·팀 인원·예산·
   데드라인)를 반드시 인용해라. 숫자 없는 이유는 근거가 없는 것이다.
5. refined_brief 안에 "이번엔 안 한다"·"범위 밖"으로 명시된 내용이 있으면 그 요소는
   defer 또는 unnecessary의 가장 강한 신호다.
6. priority는 1이 가장 중요하다. 이 프로젝트의 심장이 무엇인지 판단해서 매겨라.
7. 요소는 6~10개가 정상이다. 20개는 너무 잘게 쪼갠 것이고, 3개는 너무 뭉갠 것이다.
"""

ANALYZE_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", ANALYZE_SYSTEM_PROMPT),
        (
            "human",
            (
                "refined_brief:\n{refined_brief}\n\n"
                "일부 항목은 인터뷰에서 답을 얻지 못해 아래 가정을 썼다 (참고용):\n"
                "{assumptions}\n"
            ),
        ),
    ]
)

ANALYZE_RETRY_HINT = (
    "형식을 정확히 지켜 스키마에 맞는 JSON만 다시 출력해라. "
    "components는 최소 1개 이상이어야 하고, necessity_reason에는 제약조건 숫자를 인용해라."
)
