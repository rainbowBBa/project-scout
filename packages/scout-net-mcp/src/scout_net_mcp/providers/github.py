"""GitHub — dossier 수집: 마지막 커밋일·archived·스타·이슈 처리율
(04-아키텍처.md "MCP 툴 6종"). 토큰 없으면 60req/h, 있으면 5000req/h.
"""

import httpx

from scout_net_mcp import cache
from scout_net_mcp.config import Settings
from scout_net_mcp.egress import check_allowed

_settings = Settings()


def _headers() -> dict[str, str]:
    if _settings.github_token:
        return {"Authorization": f"Bearer {_settings.github_token}"}
    return {}


async def github_repo_health(owner: str, repo: str) -> dict:
    """저장소 상태 — repos + commits + search/issues 세 호출을 합친다."""
    cache_key = f"github-repo-health:{owner}/{repo}"
    cached = cache.get(cache_key, _settings)
    if cached is not None:
        return cached

    async with httpx.AsyncClient(headers=_headers(), timeout=10.0) as client:
        repo_url = f"https://api.github.com/repos/{owner}/{repo}"
        await check_allowed(repo_url, _settings)
        repo_resp = await client.get(repo_url)
        repo_resp.raise_for_status()
        repo_data = repo_resp.json()

        commits_url = f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=1"
        await check_allowed(commits_url, _settings)
        commits_resp = await client.get(commits_url)
        commits_resp.raise_for_status()
        commits_data = commits_resp.json()
        last_commit_at = None
        if commits_data:
            last_commit_at = commits_data[0].get("commit", {}).get("author", {}).get("date")

        closed_url = (
            f"https://api.github.com/search/issues?q=repo:{owner}/{repo}+type:issue+state:closed"
        )
        await check_allowed(closed_url, _settings)
        closed_resp = await client.get(closed_url)
        closed_resp.raise_for_status()
        closed_issues = closed_resp.json().get("total_count", 0)

    open_issues = repo_data.get("open_issues_count", 0)
    total_issues = closed_issues + open_issues
    resolution_rate = round(closed_issues / total_issues, 2) if total_issues else None

    result = {
        "full_name": repo_data.get("full_name", f"{owner}/{repo}"),
        "archived": repo_data.get("archived", False),
        "stars": repo_data.get("stargazers_count"),
        "last_commit_at": last_commit_at,
        "open_issues": open_issues,
        "closed_issues": closed_issues,
        "issue_resolution_rate": resolution_rate,
        "description": repo_data.get("description"),
    }
    cache.set(cache_key, result, _settings)
    return result
