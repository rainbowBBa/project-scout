import os
import sys
from datetime import timedelta

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
    # ★ MCP 서버 전용 설정은 이 접두사를 쓴다. 화이트리스트에 없는 이름은 자식
    # 프로세스에 **도달하지 않고** 조용히 기본값이 쓰인다 — 증상이 "환경변수가 안
    # 먹는다"로만 보이는 함정이라, `test_egress`가 두 목록의 일치를 검사한다.
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
    """MCP 서버는 인터넷을 때리는 유일한 출구다 — 응답 대기 상한이 없으면 그 요소가
    멈춘 채 남는다. 기본값을 인자로 받는 이유는 `.env`가 테스트 결과를 바꾸지
    않게 하기 위해서다 (Settings를 노드가 읽어 넘긴다).
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
