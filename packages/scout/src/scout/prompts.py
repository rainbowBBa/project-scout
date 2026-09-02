"""전 단계 공용 프롬프트 모음. schemas.py와 같은 이유로 한 파일에 모은다 — 프롬프트를
고칠 때 단계 로직(stages/<단계>.py)까지 뒤질 필요가 없다.

각 단계는 여기서 `ChatPromptTemplate`을 가져와 `prompt | llm.with_structured_output(...)`
형태로 파이프 연결한다 (CLAUDE.md "LLM 구조화 출력" 패턴).
"""

from langchain_core.prompts import ChatPromptTemplate

# ── interview ────────────────────────────────────────────────────────────

INTERVIEW_SYSTEM_PROMPT = """당신은 소프트웨어 프로젝트의 요구사항을 구체화하는 인터뷰어다.
사용자의 한 줄 설명과 5개 질문에 대한 답변을 받아 Interview 스키마를 채운다.

규칙:
1. refined_brief는 3~5문장의 새로 쓴 글이다. raw_description이나 답변을 그대로 나열하거나
   복사하면 안 된다. 예를 들어 입력이 "AI 요약 기능이 있는 팀 채팅 앱을 만들고 싶어"라면
   그 문장을 반복하지 말고, "사내 200명이 쓰는 팀 채팅 앱. 실시간 메시지 전달과 AI 요약이
   핵심 기능. 3인 TypeScript 팀이 3개월 내 출시..."처럼 답변 내용을 문장에 녹여 새로 써라.
2. must_haves와 non_goals는 최소 1개 이상씩 채운다. 사용자가 명시하지 않았다면 설명과
   답변에서 합리적으로 추론해 채운다 — 절대 비워두지 않는다.
3. assumptions에는 기본값을 쓴 항목을 모두 문장으로 적는다. 아래 "기본값 사용 항목" 목록에
   있는 각 줄을 빠짐없이 반영한다.
4. budget_monthly_usd는 숫자를 찾을 수 없으면 반드시 null이다 — **0을 쓰지 않는다.**
   0은 "예산이 0원"이라는 다른 뜻이 되어버린다. "미지정"·"모름"·"미응답"은 전부 null이다.
   team_size는 정수로, deadline_months는 숫자(개월)로 변환한다. data_sensitivity는
   public/internal/regulated 중 하나로 정규화한다.
"""

INTERVIEW_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", INTERVIEW_SYSTEM_PROMPT),
        (
            "human",
            (
                "raw_description: {raw_description}\n\n"
                "질문과 답변:\n{qa_lines}\n\n"
                "기본값 사용 항목 (assumptions에 반영):\n{defaults_block}\n"
            ),
        ),
    ]
)

INTERVIEW_RETRY_HINT = (
    "형식을 정확히 지켜 스키마에 맞는 JSON만 다시 출력해라. "
    'budget_monthly_usd를 모르면 JSON null을 써라 — 절대 문자열 "null"을 쓰지 마라.'
)

# ── analyze ──────────────────────────────────────────────────────────────

ANALYZE_SYSTEM_PROMPT = """당신은 소프트웨어 프로젝트에 필요한 요소를 도출하고, 각 요소가
정말 필요한지 판단하는 아키텍트다. interview에서 구체화된 명세를 받아 Analysis 스키마를 채운다.

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
4. necessity_reason에는 interview의 제약조건 숫자(사용자 규모·팀 인원·예산·데드라인)를
   반드시 인용해라. 숫자 없는 이유는 근거가 없는 것이다.
5. non_goals에 명시된 범위 밖은 defer 또는 unnecessary의 가장 강한 신호다 — 사용자가
   "검색은 나중에"라고 했으면 그 요소는 defer다.
6. priority는 1이 가장 중요하다. 이 프로젝트의 심장이 무엇인지 판단해서 매겨라.
7. 요소는 6~10개가 정상이다. 20개는 너무 잘게 쪼갠 것이고, 3개는 너무 뭉갠 것이다.
"""

ANALYZE_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", ANALYZE_SYSTEM_PROMPT),
        (
            "human",
            (
                "refined_brief: {refined_brief}\n\n"
                "제약조건:\n"
                "- 예상 사용자 규모: {scale}\n"
                "- 월 예산: {budget}\n"
                "- 팀: {team_size}인, 숙련 언어 {team_languages}\n"
                "- 데드라인: {deadline_months}개월\n"
                "- 데이터 민감도: {data_sensitivity}\n\n"
                "must_haves:\n{must_haves}\n\n"
                "non_goals (범위 밖 — defer/unnecessary의 신호):\n{non_goals}\n"
            ),
        ),
    ]
)

ANALYZE_RETRY_HINT = (
    "형식을 정확히 지켜 스키마에 맞는 JSON만 다시 출력해라. "
    "components는 최소 1개 이상이어야 하고, necessity_reason에는 제약조건 숫자를 인용해라."
)
