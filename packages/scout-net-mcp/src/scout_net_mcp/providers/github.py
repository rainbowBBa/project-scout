"""GitHub — dossier 수집: 마지막 커밋일·archived·기여자 수·스타·이슈 처리율
(04-아키텍처.md "MCP 툴 6종"). 토큰 없으면 60req/h, 있으면 5000req/h.
"""

import re

import httpx

from scout_net_mcp import cache
from scout_net_mcp.config import Settings
from scout_net_mcp.egress import check_allowed

_settings = Settings()


def _headers() -> dict[str, str]:
    if _settings.github_token:
        return {"Authorization": f"Bearer {_settings.github_token}"}
    return {}


_LAST_PAGE_RE = re.compile(r"[?&]page=(\d+)>;\s*rel=\"last\"")


async def _contributor_count(client: httpx.AsyncClient, owner: str, repo: str) -> int | None:
    """기여자 수 — 목록을 받지 않고 Link 헤더의 마지막 페이지 번호로 센다.

    per_page=1이므로 마지막 페이지 번호가 곧 인원수다. 전체 목록을 페이지로 다 도는
    방식은 기여자가 많은 저장소에서 호출이 수십 회로 늘어난다 (04-아키텍처.md).

    실패해도 None을 돌려준다 — 이 값 하나 때문에 나머지 사실까지 잃지 않는다
    (불변식 11). 기여자가 아주 많은 저장소는 GitHub가 403을 주고, 빈 저장소는 204다.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/contributors?per_page=1&anon=1"
    try:
        await check_allowed(url, _settings)
        resp = await client.get(url)
        if resp.status_code == 204:
            return 0
        resp.raise_for_status()
    except (httpx.HTTPError, ValueError):
        return None

    match = _LAST_PAGE_RE.search(resp.headers.get("link", ""))
    if match:
        return int(match.group(1))
    # Link가 없으면 페이지가 하나뿐 — per_page=1이라 배열 길이가 곧 0 또는 1이다.
    data = resp.json()
    return len(data) if isinstance(data, list) else None


async def github_repo_health(owner: str, repo: str) -> dict:
    """저장소 상태 — repos + commits + contributors + search/issues 네 호출을 합친다."""
    cache_key = f"github-repo-health:{owner}/{repo}"
    cached = cache.get(cache_key, _settings)
    if cached is not None:
        return cached

    async with httpx.AsyncClient(
        headers=_headers(), timeout=_settings.scout_net_http_timeout_seconds
    ) as client:
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

        contributors = await _contributor_count(client, owner, repo)

    open_issues = repo_data.get("open_issues_count", 0)
    total_issues = closed_issues + open_issues
    resolution_rate = round(closed_issues / total_issues, 2) if total_issues else None

    result = {
        "full_name": repo_data.get("full_name", f"{owner}/{repo}"),
        "archived": repo_data.get("archived", False),
        "contributors": contributors,
        "stars": repo_data.get("stargazers_count"),
        "last_commit_at": last_commit_at,
        "open_issues": open_issues,
        "closed_issues": closed_issues,
        "issue_resolution_rate": resolution_rate,
        "description": repo_data.get("description"),
    }
    cache.set(cache_key, result, _settings)
    return result
