import httpx
from mcp.server.fastmcp import FastMCP

from scout_net_mcp.config import Settings
from scout_net_mcp.egress import check_allowed

mcp = FastMCP("scout-net")
_settings = Settings()


@mcp.tool()
async def npm_package(name: str) -> dict:
    """npm 레지스트리에서 패키지 메타데이터를 조회한다 (스모크용 provider 1개)."""
    url = f"https://registry.npmjs.org/{name}"
    check_allowed(url, _settings)
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=10.0)
        response.raise_for_status()
        return response.json()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
