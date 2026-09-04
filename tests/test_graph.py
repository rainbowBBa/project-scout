"""slug 생성을 검사한다 — LLM도 네트워크도 쓰지 않는다.

검증하는 주장: **slug는 설명만의 함수다.** 폴더명이면서 체크포인터 `thread_id`이므로,
같은 설명으로 다시 실행하면 같은 값이 나와야 끝난 단계를 건너뛴다.
"""

from scout.graph import make_slug

TODAY = "2026-09-04"


def test_same_description_gives_the_same_slug():
    """★ 재개 계약 — 같은 설명이면 같은 폴더다."""
    first = make_slug("페르소나 챗봇을 만들고 싶어", today=TODAY)
    second = make_slug("페르소나 챗봇을 만들고 싶어", today=TODAY)

    assert first == second


def test_different_descriptions_do_not_collide():
    a = make_slug("팀 채팅 앱", today=TODAY)
    b = make_slug("팀 채팅 앱을 만들고 싶어", today=TODAY)

    assert a != b


def test_slug_is_date_plus_short_hash():
    """폴더명·`scout show` 인자·thread_id를 겸하므로 ASCII 짧은 형태여야 한다."""
    slug = make_slug("페르소나 생성 및 대화할수 있는 챗봇", today=TODAY)

    date, _, digest = slug.rpartition("-")
    assert date == TODAY
    assert len(digest) == 8
    assert digest.isalnum() and digest.islower(), (
        "붙여넣으면 돌아가야 한다 — 공백·한글이 들어가면 scout show가 깨진다"
    )


def test_korean_only_description_still_gets_a_slug():
    """설명에서 단어를 뽑지 않는다 — 한국어만 있어도 형태가 같다."""
    korean = make_slug("사내 200명이 쓰는 팀 채팅 앱", today=TODAY)
    english = make_slug("team chat app for 200 people", today=TODAY)

    assert len(korean) == len(english)


def test_date_separates_runs_across_days():
    same = "팀 채팅 앱"

    assert make_slug(same, today="2026-09-04") != make_slug(same, today="2026-09-05")
