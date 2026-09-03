"""개발용 LLM 캐시의 배선을 검사한다 — LLM도 네트워크도 쓰지 않는다.

설계 주장을 검증하는 6종과 성격이 다르다(그래서 07-검증.md의 표에는 없다). 그래도
테스트가 필요한 이유는 **캐시가 조용히 틀린 응답을 돌려주면 개발 판단이 오염되기**
때문이다 — 프롬프트를 고쳤는데 옛 응답이 나오면 그 프롬프트가 먹혔다고 오판한다.
"""

from langchain_core.outputs import ChatGeneration, Generation
from langchain_core.messages import AIMessage
from scout.llm_cache import SqliteLLMCache


def _cache(tmp_path) -> SqliteLLMCache:
    return SqliteLLMCache(tmp_path / "llm-cache.sqlite")


def test_roundtrip_returns_the_same_generation(tmp_path):
    cache = _cache(tmp_path)
    stored = [ChatGeneration(message=AIMessage(content="설계 요약"))]

    cache.update("프롬프트 A", "llm-1", stored)
    got = cache.lookup("프롬프트 A", "llm-1")

    assert got is not None, "저장한 응답을 못 읽었다"
    assert got[0].message.content == "설계 요약"


def test_miss_when_prompt_changes(tmp_path):
    """★ 프롬프트를 고치면 그 단계만 자동으로 미스가 된다 — 이 캐시의 무효화 전략이다."""
    cache = _cache(tmp_path)
    cache.update("프롬프트 A", "llm-1", [Generation(text="옛 응답")])

    assert cache.lookup("프롬프트 A (앵커 추가)", "llm-1") is None


def test_miss_when_llm_string_differs(tmp_path):
    """llm_string은 모델·파라미터·바인딩된 툴을 인코딩한다 — 툴셋이 다르면 키가 갈린다."""
    cache = _cache(tmp_path)
    cache.update("프롬프트 A", "llm-1", [Generation(text="응답")])

    assert cache.lookup("프롬프트 A", "llm-2") is None


def test_counts_hits_and_misses(tmp_path):
    cache = _cache(tmp_path)
    cache.update("A", "llm-1", [Generation(text="x")])

    cache.lookup("A", "llm-1")
    cache.lookup("없는 것", "llm-1")

    assert (cache.hits, cache.misses) == (1, 1)
    assert "적중 1" in cache.summary() and "미스 1" in cache.summary()


def test_survives_a_new_instance_on_the_same_file(tmp_path):
    """디스크 캐시여야 다음 실행에서 적중한다 — 인메모리면 값이 없다."""
    path = tmp_path / "llm-cache.sqlite"
    SqliteLLMCache(path).update("A", "llm-1", [Generation(text="재실행에서도 살아있다")])

    got = SqliteLLMCache(path).lookup("A", "llm-1")

    assert got is not None and got[0].text == "재실행에서도 살아있다"


def test_update_overwrites_the_same_key(tmp_path):
    cache = _cache(tmp_path)
    cache.update("A", "llm-1", [Generation(text="처음")])
    cache.update("A", "llm-1", [Generation(text="나중")])

    got = cache.lookup("A", "llm-1")

    assert got is not None and got[0].text == "나중"
