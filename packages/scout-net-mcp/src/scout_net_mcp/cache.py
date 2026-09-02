"""디스크 캐시 — TTL 만료 전까지는 같은 키에 대해 HTTP를 다시 안 보낸다.
여러 실행이 공유해 egress를 줄이고 재실행을 빠르게 한다 (04-아키텍처.md).
"""

import hashlib
import json
import time
from pathlib import Path

from scout_net_mcp.config import Settings


def _path_for(key: str, settings: Settings) -> Path:
    digest = hashlib.sha256(key.encode()).hexdigest()
    return Path(settings.scout_cache_dir) / f"{digest}.json"


def get(key: str, settings: Settings) -> dict | None:
    path = _path_for(key, settings)
    if not path.exists():
        return None
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    if age_hours > settings.scout_cache_ttl_hours:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def set(key: str, value: dict, settings: Settings) -> None:
    path = _path_for(key, settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
