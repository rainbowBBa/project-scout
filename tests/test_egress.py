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


# ── 설정이 MCP 서버 프로세스에 도달하는가 (불변식 3의 반대편) ────────────


def test_every_server_setting_passes_the_whitelist():
    """★ MCP 서버 설정을 만들고 `SERVER_ENV_KEYS`를 잊으면 값이 도달하지 않는다.

    `mcp_client._server_env`가 접두사 화이트리스트로 자식 프로세스의 환경을 만든다
    (불변식 3 — `AWS_*`를 넘기지 않는다). 그래서 새 이름이 목록에 없으면 `.env`에
    써도 **조용히 기본값이 쓰이고**, 증상이 "환경변수가 안 먹는다"로만 보인다.
    사람이 기억해야 하는 규칙을 여기서 코드가 강제한다.
    """
    from scout.mcp_client import SERVER_ENV_KEYS
    from scout_net_mcp.config import Settings as ServerSettings

    for field in ServerSettings.model_fields:
        name = field.upper()
        assert any(name == p or name.startswith(p) for p in SERVER_ENV_KEYS), (
            f"{name}이 SERVER_ENV_KEYS를 통과하지 못한다 — MCP 서버에 도달하지 않는다"
        )


def test_app_only_settings_do_not_leak_to_the_server():
    """반대 방향 — 앱 전용 설정은 서버로 가지 않아야 한다 (경계가 한 방향만이면 무의미하다)."""
    from scout.mcp_client import SERVER_ENV_KEYS

    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_DEFAULT_REGION",
        "SCOUT_MODEL_ID",
        "SCOUT_BEDROCK_READ_TIMEOUT_SECONDS",
        "SCOUT_LLM_CACHE_PATH",
    ):
        assert not any(name == p or name.startswith(p) for p in SERVER_ENV_KEYS), (
            f"{name}이 MCP 서버 프로세스로 넘어간다 — 크레덴셜 경계가 뚫린다"
        )
