"""개발용 LLM 응답 캐시 — 반복 실행에서 Bedrock 호출을 0으로 만든다.

한 번 돌리면 LLM 호출이 기본값에서 40회쯤이고 ReAct 루프가 스텝마다 이전 메시지를
다시 보내므로, 프롬프트와 무관한 반복(렌더링 확인·리팩터·뒤 단계만 고치기)에서도
일일 토큰 쿼터가 그대로 깎인다. 그 반복 비용을 없애는 장치다.

★ **캐시 키가 프롬프트 문자열이라 프롬프트를 고치면 그 단계만 자동으로 미스가 된다.**
따로 버전을 매기거나 무효화할 필요가 없다 — 딱 원하는 동작이다.

`langchain_community`의 `SQLiteCache`를 쓰지 않는 이유는 그 패키지가 설치돼 있지
않기 때문이다. 표준 라이브러리 `sqlite3`로 충분하고, MCP 서버의 디스크 캐시와 같은
패턴이라 저장 방식이 하나로 유지된다.

기본은 **off**다 (`SCOUT_LLM_CACHE=1`로 켠다). 이 도구의 값어치는 사실의 신선도이고,
같은 프롬프트+입력이면 LLM의 비결정성이 사라져 judge 품질의 편차를 볼 수 없게 된다
(001/07-검증.md 성공 기준 7·8-1·9는 캐시를 끄고 확인한다).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from langchain_core.caches import BaseCache
from langchain_core.load import dumps, loads
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import (
    ChatGeneration,
    ChatGenerationChunk,
    Generation,
    GenerationChunk,
)

# `loads`의 기본 allowlist는 앞으로 바뀐다고 경고한다. 저장되는 클래스만 명시해
# 기본값 변경에 영향받지 않게 하고 역직렬화 범위도 좁힌다
_ALLOWED = [
    ChatGeneration,
    ChatGenerationChunk,
    Generation,
    GenerationChunk,
    AIMessage,
    AIMessageChunk,
]

_DDL = """
CREATE TABLE IF NOT EXISTS llm_cache (
    prompt TEXT NOT NULL,
    llm_string TEXT NOT NULL,
    response TEXT NOT NULL,
    PRIMARY KEY (prompt, llm_string)
);
"""


class SqliteLLMCache(BaseCache):
    """`(프롬프트, llm_string)` → 응답. `llm_string`은 모델·파라미터·바인딩된 툴을
    인코딩하므로 툴셋이 다른 호출은 키가 저절로 갈린다.

    적중/미스를 세어 둔다 — 실행 끝에 CLI가 찍는다. 안 찍으면 캐시가 실제로 먹었는지
    알 수 없어서 "왜 결과가 안 바뀌지"에서 시간을 잃는다.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0
        with self._conn() as conn:
            conn.executescript(_DDL)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def lookup(self, prompt: str, llm_string: str) -> list[Generation] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT response FROM llm_cache WHERE prompt = ? AND llm_string = ?",
                (prompt, llm_string),
            ).fetchone()
        if row is None:
            self.misses += 1
            return None
        self.hits += 1
        return loads(row[0], allowed_objects=_ALLOWED)

    def update(self, prompt: str, llm_string: str, return_val: Any) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO llm_cache (prompt, llm_string, response) VALUES (?, ?, ?)
                ON CONFLICT(prompt, llm_string) DO UPDATE SET response = excluded.response
                """,
                (prompt, llm_string, dumps(return_val)),
            )

    def clear(self, **kwargs: Any) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM llm_cache")

    def summary(self) -> str:
        return f"캐시 적중 {self.hits} / 미스 {self.misses}"
