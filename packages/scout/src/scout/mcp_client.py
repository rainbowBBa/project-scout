import os
import sys

from langchain_mcp_adapters.client import MultiServerMCPClient

# MCP 서버 프로세스에 넘길 환경변수 화이트리스트 — AWS_* 는 절대 포함하지 않는다
# (08-설정.md ★ 크레덴셜 경계를 stdio에서 강제하는 방법).
# PATH/SystemRoot는 크레덴셜이 아니라 Windows에서 자식 프로세스가 뜨는 데 필요한 값이다.
SERVER_ENV_KEYS = (
    "GITHUB_TOKEN",
    "SCOUT_EGRESS_",
    "SCOUT_CACHE_",
    "SCOUT_RATE_",
    "SCOUT_SEARCH_PROVIDER",
    "PATH",
    "SystemRoot",
)


def _server_env() -> dict[str, str]:
    return {
        k: v
        for k, v in os.environ.items()
        if any(k == p or k.startswith(p) for p in SERVER_ENV_KEYS)
    }


def make_mcp_client() -> MultiServerMCPClient:
    return MultiServerMCPClient(
        {
            "scout-net": {
                "command": sys.executable,
                "args": ["-m", "scout_net_mcp.server"],
                "transport": "stdio",
                "env": _server_env(),
            }
        }
    )
