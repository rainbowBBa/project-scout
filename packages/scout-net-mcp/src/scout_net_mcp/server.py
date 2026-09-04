"""scout-net MCP 서버 — project-scout의 유일한 인터넷 출구 (04-아키텍처.md).

`scout`를 import하지 않는다 (불변식 1). 전송은 stdio만 쓴다.
"""

from mcp.server.fastmcp import FastMCP

from scout_net_mcp.providers import github, npm, osv, pypi, search

mcp = FastMCP("scout-net")

mcp.tool()(npm.npm_search)
mcp.tool()(npm.npm_package)
mcp.tool()(pypi.pypi_package)
mcp.tool()(github.github_repo_health)
mcp.tool()(osv.osv_query)
mcp.tool()(search.web_search)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
