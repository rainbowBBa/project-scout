import pytest
from scout_net_mcp.config import Settings
from scout_net_mcp.egress import check_allowed


def _settings(tmp_path) -> Settings:
    return Settings(
        scout_egress_allowlist="registry.npmjs.org,pypi.org",
        scout_cache_dir=str(tmp_path),
    )


async def test_allowed_host_passes(tmp_path):
    await check_allowed("https://registry.npmjs.org/socket.io", _settings(tmp_path))


async def test_disallowed_host_rejected(tmp_path):
    with pytest.raises(PermissionError):
        await check_allowed("https://evil.example.com/x", _settings(tmp_path))


async def test_audit_log_records_both_outcomes(tmp_path):
    settings = _settings(tmp_path)

    await check_allowed("https://registry.npmjs.org/socket.io", settings)
    with pytest.raises(PermissionError):
        await check_allowed("https://evil.example.com/x", settings)

    log_text = (tmp_path / "audit.log").read_text(encoding="utf-8")
    lines = log_text.strip().splitlines()
    assert len(lines) == 2
    assert "ALLOW registry.npmjs.org" in lines[0]
    assert "DENY evil.example.com" in lines[1]
