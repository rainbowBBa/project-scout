import asyncio
import os

import boto3
import typer
from langchain_aws import __version__ as langchain_aws_version
from pydantic import ValidationError

from scout.config import Settings
from scout.llm import make_llm
from scout.mcp_client import make_mcp_client

app = typer.Typer()


@app.callback()
def callback() -> None:
    """project-scout — 만들고 싶은 소프트웨어를 근거와 함께 답하는 CLI."""


@app.command()
def doctor() -> None:
    """AWS 자격·리전·모델·동시쿼터·MCP 스모크를 확인한다."""
    asyncio.run(_doctor())


async def _doctor() -> None:
    typer.echo("== scout doctor ==")

    try:
        settings = Settings()
    except ValidationError as e:
        typer.echo(f"[FAIL] Settings 로딩 실패 — 필수 변수(AWS_REGION 등)를 확인하세요:\n{e}")
        raise typer.Exit(code=1) from None

    typer.echo(f"[OK] AWS_REGION={settings.aws_region}")

    has_key = bool(os.environ.get("AWS_BEARER_TOKEN_BEDROCK"))
    typer.echo(f"Bedrock API key: {'설정됨' if has_key else '미설정'} (값은 출력하지 않음)")
    typer.echo(f"boto3: {boto3.__version__}")
    typer.echo(f"langchain-aws: {langchain_aws_version}")

    session_kwargs: dict[str, str] = {"region_name": settings.aws_region}
    if settings.aws_profile:
        session_kwargs["profile_name"] = settings.aws_profile
    session = boto3.Session(**session_kwargs)

    try:
        identity = session.client("sts").get_caller_identity()
        typer.echo(f"[OK] sts get-caller-identity: {identity['Arn']}")
    except Exception as e:  # noqa: BLE001 — doctor는 원인 불문 다음 확인으로 넘어가야 한다
        typer.echo(f"[SKIP] AWS 인증 확인 실패 — {e}")
        typer.echo("      .env 의 AWS_PROFILE 또는 AWS_BEARER_TOKEN_BEDROCK 을 채운 뒤 다시 실행하세요.")
        await _mcp_smoke()
        return

    try:
        models = session.client("bedrock").list_foundation_models()
        matches = sorted(
            m["modelId"] for m in models["modelSummaries"] if "sonnet" in m["modelId"].lower()
        )
        typer.echo(f"[OK] ListFoundationModels — sonnet 계열 모델 {len(matches)}개")
        for model_id in matches[:5]:
            typer.echo(f"      {model_id}")
    except Exception as e:  # noqa: BLE001 — doctor는 원인 불문 다음 확인으로 넘어가야 한다
        typer.echo(f"[FAIL] ListFoundationModels 실패: {e}")

    try:
        llm = make_llm(settings)
        result = await llm.ainvoke("ping")
        typer.echo(f"[OK] Sonnet 1회 호출 성공 ({len(str(result.content))} chars)")

        results = await asyncio.gather(*[llm.ainvoke("ping") for _ in range(4)])
        typer.echo(f"[OK] Sonnet 4병렬 호출 성공 ({len(results)}개 응답, 동시 쿼터 확인됨)")
    except Exception as e:  # noqa: BLE001 — doctor는 원인 불문 다음 확인으로 넘어가야 한다
        typer.echo(f"[FAIL] Bedrock 호출 실패: {e}")

    await _mcp_smoke()


async def _mcp_smoke() -> None:
    try:
        client = make_mcp_client()
        tools = await client.get_tools()
        tool_map = {t.name: t for t in tools}
        result = await tool_map["npm_package"].ainvoke({"name": "socket.io"})
        typer.echo(f"[OK] MCP npm_package(socket.io) 응답 수신 ({len(str(result))} chars)")
    except Exception as e:  # noqa: BLE001 — doctor는 원인 불문 다음 확인으로 넘어가야 한다
        typer.echo(f"[FAIL] MCP 스모크 실패: {e}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
