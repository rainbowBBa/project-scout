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
