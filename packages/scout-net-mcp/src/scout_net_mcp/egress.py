"""인터넷 출구 통제 — allowlist·토큰버킷 레이트리밋·감사로그
(04-아키텍처.md "서버측 공통 인프라"). scout_net_mcp의 모든 provider가
실제 요청을 보내기 전 반드시 이 모듈을 거친다.
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from scout_net_mcp.config import Settings


@dataclass
class _TokenBucket:
    """초당 rate개씩 채워지는 토큰버킷. capacity까지 순간 버스트를 허용한다."""

    rate: float
    capacity: float
    tokens: float = field(init=False)
    updated_at: float = field(init=False)

    def __post_init__(self) -> None:
        self.tokens = self.capacity
        self.updated_at = time.monotonic()

    async def acquire(self) -> None:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated_at) * self.rate)
        self.updated_at = now
        if self.tokens < 1:
            wait = (1 - self.tokens) / self.rate
            await asyncio.sleep(wait)
            self.tokens = 0
            self.updated_at = time.monotonic()
        else:
            self.tokens -= 1


# 호스트별 버킷 — GitHub가 바쁘다고 npm까지 느려지면 안 된다
_buckets: dict[str, _TokenBucket] = {}


def _bucket_for(host: str, settings: Settings) -> _TokenBucket:
    if host not in _buckets:
        _buckets[host] = _TokenBucket(
            rate=settings.scout_rate_limit_rps, capacity=settings.scout_rate_limit_rps
        )
    return _buckets[host]


def _audit_log_path(settings: Settings) -> Path:
    return Path(settings.scout_cache_dir) / "audit.log"


def _audit(*, url: str, host: str, allowed: bool, settings: Settings) -> None:
    path = _audit_log_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    verdict = "ALLOW" if allowed else "DENY"
    line = f"{datetime.now(UTC).isoformat()} {verdict} {host} {url}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


async def check_allowed(url: str, settings: Settings) -> None:
    """allowlist 확인 + 감사로그 기록 + (허용 시) 레이트리밋 대기.

    거부되면 `PermissionError`. 실패를 `gaps`로 격하하는 것은 앱 쪽 책임이다 —
    이 패키지는 `scout`를 import하지 않는다 (불변식 1).
    """
    host = urlparse(url).hostname or ""
    allowlist = {h.strip() for h in settings.scout_egress_allowlist.split(",") if h.strip()}
    allowed = host in allowlist
    _audit(url=url, host=host, allowed=allowed, settings=settings)
    if not allowed:
        raise PermissionError(f"egress 거부: {host} 는 allowlist 밖입니다 ({sorted(allowlist)})")
    await _bucket_for(host, settings).acquire()
