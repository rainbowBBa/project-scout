# STEP 00 · 환경

> uv 워크스페이스 두 패키지를 세우고 `.env`·`Settings`로 설정을 잡은 뒤 Bedrock 연결을 확인한다.
> MCP 서버는 스켈레톤만 만들어 인터넷 출구가 열리는지 30분 안에 답한다.

**선행** 없음 · **시간** ~1.5h · **설계** [08-설정](../001_기술스택-조사-에이전트-설계/08-설정.md) · [05-프로젝트관리](../001_기술스택-조사-에이전트-설계/05-프로젝트관리.md)

## 만들 것
- `pyproject.toml` (루트) — `[tool.uv.workspace]` · `[tool.ruff]` · `[tool.ty]`
- `.python-version` (3.12) · `.gitignore` · `README.md`
- **`.env.example`** — [08-설정](../001_기술스택-조사-에이전트-설계/08-설정.md)의 전문 그대로. `.env`는 복사해서 채운다
- `packages/scout/pyproject.toml` — httpx 없음, `pydantic-settings` 포함, `TID251` banned-api
- `packages/scout-net-mcp/pyproject.toml` — langchain 없음
- **`scout/config.py`** — `Settings(BaseSettings)`. AWS 크레덴셜은 담지 않는다
- `scout/cli.py` — `doctor` 서브커맨드만
- `scout_net_mcp/server.py` — FastMCP + `npm_package` 1개 (스모크용)

## 완료 기준
- [x] `uv sync` 성공, `uv sync --package scout-net-mcp` 가 langchain 없이 성공
- [x] **`AWS_DEFAULT_REGION` 없이 실행하면 시작 시 실패한다** (`BaseSettings` 필수 검증)
- [x] `SCOUT_MAX_COMPONENTS=abc` 로 두면 타입 오류로 잡힌다
- [x] `doctor` 가 인증 방식을 찍는다 — `sts get-caller-identity` · API key **존재 여부만** · boto3/langchain-aws 버전
- [ ] `doctor` 가 `ListFoundationModels` 로 모델 ID 형태를 확정한다 — **AWS 자격 미설정이라 미확인.**
      `.env`에 `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`를 채운 뒤 `uv run scout doctor`로 확인
- [ ] Sonnet 1회 호출 + **4병렬 호출** 성공 (동시 쿼터 확인) — 위와 동일한 이유로 미확인
- [x] MCP 스모크: `npm_package("socket.io")` 응답, allowlist 밖 도메인 거부
      (거부는 `tests/test_egress.py`로 검증 — allowlist 체크가 npm_package 호스트 하나뿐이라
      doctor에서 직접 거부를 재현할 수단이 없어 별도 pytest로 분리)
- [x] `.gitignore` 에 `.env` 가 있고 `git status` 에 `.env` 가 안 뜬다
- [x] `uv run ruff check` 통과, `uv run ty check` 결과 확인 (오탐 없음, 게이트 아님으로 유지)

## 막히면
인증이 둘 다 없으면 여기서 막힌다 — 사내 계정이 SigV4인지 API key인지 먼저 확인.
모델 ID 형태 3가지 중 무엇인지 계정마다 다름 → `doctor`가 찍은 값을 `.env`에 고정.
`uv` 미설치 → `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`
