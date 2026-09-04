import os
import sys
from datetime import timedelta

from langchain_mcp_adapters.client import MultiServerMCPClient

# MCP 서버 프로세스에 넘길 환경변수 — AWS_* 는 포함하지 않는다 (불변식 3).
# PATH/SystemRoot는 Windows에서 자식 프로세스가 뜨는 데 필요하다.
SERVER_ENV_KEYS = (
    "GITHUB_TOKEN",
    "SCOUT_EGRESS_",
    "SCOUT_CACHE_",
    "SCOUT_RATE_",
    "SCOUT_SEARCH_PROVIDER",
    # 서버 전용 설정의 접두사. 여기 없는 이름은 자식 프로세스에 도달하지 않고
    # 조용히 기본값이 쓰인다 — `test_egress`가 두 목록의 일치를 검사한다
    "SCOUT_NET_",
    "PATH",
    "SystemRoot",
)


def _server_env() -> dict[str, str]:
    return {
        k: v
        for k, v in os.environ.items()
        if any(k == p or k.startswith(p) for p in SERVER_ENV_KEYS)
    }


def make_mcp_client(read_timeout_seconds: int | None = None) -> MultiServerMCPClient:
    """`read_timeout_seconds`가 없으면 서버가 hang할 때 그 결정 지점이 멈춘 채 남는다.

    값을 인자로 받는다 — 노드가 Settings를 읽어 넘긴다.
    """
    session_kwargs = (
        {}
        if read_timeout_seconds is None
        else {"read_timeout_seconds": timedelta(seconds=read_timeout_seconds)}
    )
    return MultiServerMCPClient(
        {
            "scout-net": {
                "command": sys.executable,
                "args": ["-m", "scout_net_mcp.server"],
                "transport": "stdio",
                "env": _server_env(),
                "session_kwargs": session_kwargs,
            }
        }
    )
