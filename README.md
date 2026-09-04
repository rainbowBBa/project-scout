# project-scout

**만들고 싶은 소프트웨어를 한 줄로 설명하면, 어떻게 만들어야 하는지 근거와 함께 답하는 CLI.**

```
$ uv run scout
프로젝트 설명 입력: 이미지 분석 및 생성 기능이 있는 챗봇을 회사 ai api를 이용해서 만들고 싶어

  ... 되묻기 몇 번 → 설계 → 후보 조사 → 판정 → 순위 ...

리포트: runs/20260904-a636228c/report.html
```

나오는 것은 후보 목록이 아니라 **"이렇게 만들면 되겠다"는 설계**다. 그리고 그 설계의
모든 선택에 **근거 URL과 조회 날짜**가 붙어 있다.

---

## 1. 무엇을 해결하나

새 프로젝트의 스택을 정할 때 이런 일이 생긴다.

| 흔한 방법 | 문제 |
|---|---|
| 구글링 + 블로그 + GitHub 별 개수 | 며칠이 걸리고, 정한 뒤에 근거가 남지 않는다 |
| LLM에 물어보기 | 학습 시점 이후를 모르고, 근거를 못 낸다. 틀렸는지 알 방법이 없다 |

`project-scout`는 **사실 수집은 코드가, 판단만 LLM이** 한다.

- 마지막 릴리스 날짜 · 기여자 수 · 취약점 건수는 코드가 npm·PyPI·GitHub·OSV에서 직접 가져온다
- LLM은 **코드가 모아둔 사실만 인용할 수 있고**, 그 인용이 실제로 있는지 코드가 SQL로 다시 검사한다
- 성숙도·위험도 점수는 코드가 계산한다 (LLM이 낡은 사실을 무시해도 계산이 잡는다)

그래서 6개월 뒤에 "왜 이걸 골랐나"를 물어도 답할 수 있다.

**남다른 점 하나** — "지금 만들지 않아도 되는 것"을 먼저 알려준다. 안 만든 기능이 가장
큰 절약이다.

---

## 2. 답이 어떻게 생겼나

`runs/<실행>/report.html` — 브라우저로 열면 되는 파일 한 장이다. 외부 CDN도 자바스크립트도
쓰지 않아서 인터넷 없이도 열리고, 그대로 첨부해 공유할 수 있다.

내용은 세 묶음이다.

| 묶음 | 담긴 것 | 언제 보나 |
|---|---|---|
| **결론** | 권장 설계 (구조 · 데이터 흐름 · 구축 순서) · 선택한 기술 표 | 이것만 읽어도 된다 |
| **전제** | 이미 정해진 것 · 지금 만들지 않아도 되는 것 · 이번에 다루지 않은 것 | 이 결론이 무엇을 깔고 있나 |
| **근거** | 결정 지점별 후보 비교 · 탈락 사유 · 수집한 사실 전체 | 못 믿으면 여기를 본다 |

"선택한 기술" 표의 한 행은 이렇게 생겼다.

```
결정 지점                  고른 것         종합    이유
프론트엔드 프로토타이핑 …    gradio (근접)   ███ 5   ▶ gh.issue_close_rate=0.98로 Streamlit(0.81)…
```

- `근접` — 1위와 2위의 점수 차이가 작다는 뜻이다. 2위도 합리적 선택지다
- `5` 옆의 배지 — 그 숫자를 **코드가 계산**했는지 **LLM이 판단**했는지 구분해서 표시한다
- `▶` — 펼치면 선정 이유 전문과 점수 근거가 나온다

배지에 마우스를 올리면 뜻이 뜨고, 인쇄하면 접힌 내용이 모두 펼쳐진다.

---

## 3. 어떻게 돌아가나 — 6단계

```
interview → design → search → verify → evaluate → report
   요청      구현설계   후보     판정     점수·순위   권장설계
 구체화   +결정지점  +사실수집  +인용검증  +설계확정    HTML
```

| 단계 | 하는 일 |
|---|---|
| **interview** | 되묻는다. "사용자 규모?" "예산?" "팀 인원과 숙련 언어?" — 판정이 갈리는 건 기술이 아니라 제약조건이다 |
| **design** | 먼저 **구현 설계**를 세운다. 그 안에서 "비교해서 골라야 할 지점"(결정 지점)을 뽑는다 |
| **search** | 결정 지점마다 후보를 찾고, 후보마다 사실을 모아 **자료철(dossier)**을 만든다 |
| **verify** | 자료철을 읽고 후보마다 판정한다. **자료철 밖은 인용할 수 없다** |
| **evaluate** | 점수와 순위를 매기고, 조사 결과로 설계를 **수정해 확정**한다 |
| **report** | `scout.db`를 HTML로 렌더링한다. 이 단계는 LLM을 쓰지 않는다 |

비유는 **법정**이다 — 판사(`verify`)가 자료철(`search`)을 읽고 판정하고, 자료철 밖은
인용할 수 없다.

인터넷으로 나가는 출구는 **별도 프로세스(MCP 서버) 하나**뿐이다. 그 프로세스에는 AWS
키를 넘기지 않고, 나갈 수 있는 호스트도 목록으로 제한된다.

---

## 4. 준비물

| 필요한 것 | 확인 방법 |
|---|---|
| [uv](https://docs.astral.sh/uv/) | `uv --version`. Python 3.14는 uv가 알아서 받아온다 |
| AWS 자격 증명 | Bedrock을 호출할 수 있는 액세스 키 |
| Bedrock 모델 접근 권한 | 계정에서 Claude Sonnet 계열이 **활성화**돼 있어야 한다 |

모델 ID는 계정마다 형태가 다르다 (`anthropic.claude-sonnet-5` ·
`us.anthropic.claude-sonnet-4-6` · ARN). **직접 쓸 수 있는 값은 `scout doctor`가
찍어준다** — 추측하지 말고 그걸 쓴다.

---

## 5. 설치

```bash
git clone <이 저장소>
cd project-scout

cp .env.example .env      # 값을 채운다 (아래 참고)
uv sync                   # 의존성 설치 (Python 3.14 자동 조달)
```

`.env`에서 **반드시 채워야 하는 것은 세 개**다. 나머지는 전부 기본값이 있으니 지워도 된다.

```bash
AWS_DEFAULT_REGION=us-east-1
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
```

> `.env`는 커밋되지 않는다(`.gitignore`). 크레덴셜은 로그·보고서에도 찍히지 않는다.

설치가 끝나면 **먼저 진단을 돌린다.**

```bash
uv run scout doctor
```

```
== scout doctor ==
[OK] AWS_DEFAULT_REGION=us-east-1
AWS Access Key: 설정됨 (값은 출력하지 않음)
[OK] sts get-caller-identity: arn:aws:iam::...:user/...
[OK] ListFoundationModels — sonnet 계열 모델 4개
      anthropic.claude-sonnet-4-6
      anthropic.claude-sonnet-5            ← 이 목록에서 골라 SCOUT_MODEL_ID에 넣는다
[OK] Sonnet 1회 호출 성공 (4 chars)
[OK] 4병렬 호출 성공 (4개 응답, 동시 쿼터 확인됨)
[OK] MCP npm_package(socket.io) 응답 수신 (374 chars)
```

`[OK]`가 전부 나오면 준비가 끝났다. `[FAIL]`이 있으면 아래 [문제 해결](#9-문제-해결)을 본다.

---

## 6. 첫 실행

```bash
uv run scout
```

설명을 물어본다. **한 줄이면 된다.** 다만 정보를 많이 넣으면 되묻기가 줄어든다.

```
프로젝트 설명 입력: 사내 200명이 쓸 팀 채팅 앱을 만들고 싶어
```

### 되묻는다

```
? 예상 사용자 규모가 어느 정도인가요? 사내 200명
? 팀 인원과 숙련 언어는? 3인, TypeScript
? 월 인프라 예산은? $200
```

- **모르면 빈 입력으로 넘긴다** — 알아서 합리적으로 가정하고, 그 가정을 리포트에 기록한다
- 설명에 이미 답이 있으면 그 질문은 하지 않는다
- 기본 상한은 5번이다 (`SCOUT_INTERVIEW_MAX_TURNS`)

### 웹검색은 사람이 승인한다

npm·PyPI·GitHub·OSV 조회는 **패키지 이름만** 나가므로 그냥 진행한다. 하지만 자유
텍스트 웹검색은 물어본다.

```
  ? 인터넷 검색 "Gradio vs Streamlit image upload 2026" — 허용할까요? [y/N]
```

- 거부하면 **그 요청은 실제로 나가지 않는다.** 대신 지금까지 모은 사실로 결론을 낸다
- 거부해도 파이프라인은 계속 돈다
- 예산이 있다 — `design`은 실행 전체 3회, `search`는 결정 지점당 5회

물어보는 동안 다른 진행 표시는 잠시 멈춘다. 질문이 화면 위로 밀려 올라가지 않는다.

### 진행 상황

각 단계가 끝날 때마다 무엇을 했는지 찍는다.

```
[설계] 단계를 종료합니다.
  설계: 회사 AI API를 LangChain 래퍼로 감싸 …
  통과 3개
    [library] 프론트엔드 프로토타이핑 프레임워크 (essential, priority 1)
      정할 것: 채팅 UI와 이미지 업로드를 감당할 프레임워크는 무엇인가
      보기: Gradio vs Streamlit vs Next.js
```

### 끝나면

```
리포트: runs/20260904-a636228c/report.html
```

브라우저로 열면 된다.

> **얼마나 걸리나** — 기본 규모에서 LLM을 약 40회, 인터넷 조회를 수십 회 부른다.
> 초가 아니라 분 단위다. 급하면 아래 [규모 조절](#8-규모와-비용-조절)을 본다.

---

## 7. 결과가 어디에 남나

```
runs/20260904-a636228c/
├── report.html          ← 사람이 보는 것
├── scout.db             ← 산출물 전부 (sqlite, 11개 테이블)
└── checkpoints.sqlite   ← 어디까지 돌았나 (재개용)
```

폴더 이름은 `<년월일>-<설명 해시 8자>`다. 설명에서 단어를 뽑지 않는다 — 읽을 이름은
리포트 제목이 맡는다.

### 같은 설명으로 다시 돌리면 이어서 돈다

폴더 이름이 **날짜와 설명만의 함수**라서, 같은 날 같은 설명으로 다시 실행하면 같은
폴더를 쓰고 **이미 끝난 단계를 건너뛴다.** 중간에 끊겼을 때 그냥 다시 돌리면 된다.

처음부터 다시 돌리려면 폴더를 지우거나 설명을 바꾼다.

### 중간 산출물을 직접 보기

```bash
uv run scout show 20260904-a636228c design     # 설계 + 결정 지점
uv run scout show 20260904-a636228c search     # 후보 + 수집한 사실
uv run scout show 20260904-a636228c verify     # 판정 + 인용
uv run scout show 20260904-a636228c evaluate   # 점수 + 순위 + 확정 설계
```

해당 단계가 쓴 테이블을 JSON으로 찍는다. `scout.db`를 DB Browser for SQLite 같은
GUI로 직접 열어도 된다.

---

## 8. 규모와 비용 조절

**코드를 고치지 않는다.** 플래그나 `.env`로 조절한다.

```bash
# 작게 — 빠르고 싸다
uv run scout run "..." --max-components 1 --max-candidates 2

# 크게 — 결정 지점 8개, 지점마다 후보 5개
uv run scout run "..." --max-components 8 --max-candidates 5

# 앞부분만 보고 싶다
uv run scout run "..." --stop-after design
```

| 손잡이 | 기본값 | 뜻 |
|---|---|---|
| `--max-components` | 3 | 비교할 결정 지점 개수 |
| `--max-candidates` | 3 | 결정 지점마다 조사할 후보 개수 |
| `--stop-after` | (없음) | 이 단계까지만 돌린다 |
| `--auto-approve-search` | 꺼짐 | 웹검색 승인을 자동 통과 (비대화형 실행용) |

전체 설정 항목은 `.env.example`과
[docs/001/08-설정](docs/001_기술스택-조사-에이전트-설계/08-설정.md)에 있다.

---

## 9. 문제 해결

| 증상 | 원인과 대처 |
|---|---|
| `doctor`의 `sts get-caller-identity` 실패 | 액세스 키가 잘못됐거나 만료됐다. `.env`의 세 값을 다시 확인한다 |
| `AccessDeniedException` | 그 모델이 계정에서 활성화되지 않았다. `doctor`가 찍은 목록에서 다른 ID를 골라 `SCOUT_MODEL_ID`에 넣는다 |
| `on-demand throughput isn't supported` | 크로스리전 프로파일이 필요하다 — 모델 ID 앞에 `us.`가 붙은 값을 쓴다 |
| 읽기 타임아웃 | `SCOUT_BEDROCK_READ_TIMEOUT_SECONDS`를 올린다 (기본 600초) |
| GitHub 조회가 자주 실패 | 인증 없이 쓰면 시간당 60회 제한이다. `.env`에 `GITHUB_TOKEN`을 넣으면 5,000회가 된다 |
| 리포트에 "해당 없음"이 많다 | 정상일 수 있다 — 없는 것을 없다고 말하는 게 보고서의 일이다. `gaps`에 이유가 남는다 (`scout show <slug> search`) |
| 결과가 다 아는 내용만 나온다 | 설명이 너무 짧아 되묻기로도 제약이 안 잡힌 것이다. 규모·예산·팀·기간을 설명에 직접 넣어본다 |

인터넷 조회가 실패해도 **파이프라인은 죽지 않는다.** 못 구했다고 기록하고 계속한다 —
사실을 못 구한 것도 정보다.

---

## 10. 더 읽을 것

| 알고 싶은 것 | 어디 |
|---|---|
| 왜 만드는가 · 사용자 · 가치 | [SERVICE.md](SERVICE.md) |
| 각 단계가 정확히 무엇을 하나 | [docs/001/stages](docs/001_기술스택-조사-에이전트-설계/stages/README.md) |
| 설계 전체 · DB 스키마 · 아키텍처 | [docs/001](docs/001_기술스택-조사-에이전트-설계/README.md) |
| 설정 항목 전체 | [docs/001/08-설정](docs/001_기술스택-조사-에이전트-설계/08-설정.md) |
| 설계가 왜 이렇게 됐나 | [docs/001/CHANGELOG](docs/001_기술스택-조사-에이전트-설계/CHANGELOG.md) |
| 개발 규칙 · 불변식 (기여하려면) | [CLAUDE.md](CLAUDE.md) |
| 지금 무엇을 만들 차례인가 | [docs/002](docs/002_개발계획/README.md) |

---

## 11. 개발

```bash
uv sync                                        # 전체 설치
uv sync --package scout-net-mcp                # MCP 서버만 (DMZ 배포 리허설)

uv run ruff check --fix . && uv run ruff format .
uv run pytest                                  # 게이트
uv run ty check                                # 정보용 — 게이트 아님
```

개발 중에는 규모를 줄이고 LLM 캐시를 켠다. 코드는 고치지 않는다.

```bash
# .env
SCOUT_INTERVIEW_MAX_TURNS=2
SCOUT_LLM_CACHE=1              # 2회차부터 Bedrock 호출 0

uv run scout run "..." --max-components 1 --max-candidates 2 --auto-approve-search
```

캐시 키가 프롬프트 문자열이라 **프롬프트를 고치면 그 단계만 자동으로 미스**가 된다.
단, **판단 품질을 볼 때는 캐시를 끈다** — 비결정성이 사라져 판정의 편차를 못 본다.

기여 전에 [CLAUDE.md](CLAUDE.md)의 **불변식**을 읽는다. 각 항목이 설계의 특정 결정을
지탱하고 있어서, 이유를 모르면 "불편한데 바꿀까"에서 무너진다.

**스택** — AWS Bedrock (Claude Sonnet) · LangGraph · MCP · sqlite3 · jinja2 ·
uv 워크스페이스 · Python 3.14
