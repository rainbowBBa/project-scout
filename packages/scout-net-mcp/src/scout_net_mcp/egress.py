from urllib.parse import urlparse

from scout_net_mcp.config import Settings


def check_allowed(url: str, settings: Settings) -> None:
    """url의 호스트가 allowlist 밖이면 거부한다. 레이트리밋·감사로그는 STEP-04에서 추가."""
    host = urlparse(url).hostname
    allowlist = {h.strip() for h in settings.scout_egress_allowlist.split(",") if h.strip()}
    if host not in allowlist:
        raise PermissionError(f"egress 거부: {host} 는 allowlist 밖입니다 ({sorted(allowlist)})")
