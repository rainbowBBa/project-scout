# project-scout

만들고 싶은 소프트웨어를 한 줄로 설명하면, 어떻게 만들어야 하는지 **근거와 함께** 답하는 CLI.

자세한 설계와 개발 규칙은 [CLAUDE.md](CLAUDE.md) · [SERVICE.md](SERVICE.md) ·
[docs/](docs/) 참고.

## 설치

```bash
cp .env.example .env   # 값을 채운다 (AWS_REGION 필수)
uv sync
```

## 명령

```bash
uv sync                           # 전체 설치 (Python 3.12 자동 조달)
uv sync --package scout-net-mcp   # MCP 서버만 단독 설치 (배포 리허설)
uv run ruff check --fix . && uv run ruff format .
uv run ty check                   # 정보용 — 게이트 아님
uv run pytest

uv run scout doctor               # AWS 자격·리전·모델·동시쿼터·MCP 스모크 확인
uv run scout run "..."            # 기본 규모: 요소 3개 · 후보 8~10개
uv run scout run "..." --max-components 8 --max-candidates 5
```
