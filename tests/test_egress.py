import pytest
from scout_net_mcp.config import Settings
from scout_net_mcp.egress import check_allowed


def _settings() -> Settings:
    return Settings(scout_egress_allowlist="registry.npmjs.org,pypi.org")


def test_allowed_host_passes():
    check_allowed("https://registry.npmjs.org/socket.io", _settings())


def test_disallowed_host_rejected():
    with pytest.raises(PermissionError):
        check_allowed("https://evil.example.com/x", _settings())
