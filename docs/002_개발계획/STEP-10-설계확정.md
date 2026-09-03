# STEP 10 · 설계 확정

> `evaluate` 끝에 LLM 1회를 더 붙여, `design`의 기본틀을 조사 결과로 **수정해 확정**한다.
> 단계는 6개 그대로다 — 새 노드를 만들지 않는다.

**선행** STEP 09 · **시간** ~1.25h · **설계** [stages/4-evaluate](../001_기술스택-조사-에이전트-설계/stages/4-evaluate.md) "4. 설계 확정"

## 만들 것

- `scout/schemas.py` — `FinalDesign` 신설 (필드 9개)
  ```python
  summary · shape · data_flow · changes_from_design ·
  stack_rationale · integration_notes · combination_risks · build_order · unresolved
  ```
  `shape`·`data_flow`는 `Architecture`와 **같은 이름**이다 — v1↔v2 대조가 필드
  단위로 성립해야 한다
- `scout/store.py` — `final_designs` 테이블 + `upsert_final_design` / `get_final_design`.
  `designs` 행은 **건드리지 않는다**
- `scout/state.py` — `+ final_design`
- `scout/prompts.py` — `FINALIZE_PROMPT` · `FINALIZE_RETRY_HINT`
- `scout/stages/evaluate.py` — `evaluate_node`가 요소별 픽을 **저장한 뒤** 확정 1회
- `scout/cli.py` — evaluate 요약에 `FinalDesign.summary` 추가

## 프롬프트에 넣는 재료

| 재료 | 출처 | 왜 |
|---|---|---|
| `Architecture` | `designs` | **수정의 출발점.** `shape`·`data_flow`를 여기서 물려받는다 |
| 요소별 `winner` + `winner_reason` | `picks` | **이미 끝난 판단.** 다시 하지 않고 인용한다 |
| `needs_comparison=false` 결정 지점 | `components` | 설계가 깔고 있는 전제 |
| 통과 후보의 `cons` · `caveats` | `verdicts` | 구조 전제를 깨뜨리는 게 있는지 — **수정의 근거** |
| 승자 없는 요소 · 통과 못한 요소 | `picks` · `components` | `unresolved`의 재료 |
| `refined_brief` | `runs` | 조합 판단에 쓸 제약조건 |

### 앵커 1 — 바꿀 근거가 없으면 바꾸지 않는다

```
shape·data_flow 는 Architecture 를 출발점으로 쓴다. 조사 결과에 근거가 있을 때만
고치고, 고쳤으면 changes_from_design 에 이유와 근거를 쓴다.
  ✘ 문장을 매끄럽게 다시 쓰는 것은 변경이 아니다 — 근거 없는 재작성 금지
  ✔ verdicts 의 cons·caveats 또는 탈락 사유가 구조 전제를 깨뜨렸을 때만 고친다
```

이게 없으면 judge가 매번 설계 산문을 새로 쓰고 `changes_from_design`이
"표현을 다듬었다"로 채워진다 — **정말 바뀐 게 무엇인지** 알 수 없게 된다.

### 앵커 2 — `combination_risks`는 `cons`의 사본이 아니다

```
✘  "socket.io는 독자 프로토콜을 쓴다"            ← verdicts.cons 에 이미 있다
✔  "단일 프로세스 전제가 깨지면 socket.io는 어댑터가 필요해지고,
    PostgreSQL만으로 버티려던 전제도 함께 흔들린다"   ← 두 선택이 얽혀 생긴 위험
```

이 반례가 없으면 judge가 `cons`를 재활용하고, 사용자는 같은 문장을 두 번 읽는다.

## 완료 기준

> **상태 (2026-09-03)** — 코드 완료(`5b55985`) · **E2E 완주로 내용까지 확인**.
> 이 E2E는 토큰 쿼터 때문에 Haiku로 돌렸다 — 배선과 조립은 확인됐지만
> **판단 품질은 정본 모델(Sonnet)에서 다시 본다**
> ([08-설정](../001_기술스택-조사-에이전트-설계/08-설정.md) "SCOUT_MODEL_ID").

### 구조 · 저장 · 실패 처리 (LLM 없이 확인됨)

- [x] `designs` 행이 **덮어쓰이지 않는다** (`shape`를 SELECT 해서 확인)
      → 스모크로 확인 + **실행에서도 v1 ≠ v2**로 필드 단위 대조가 성립했다
- [x] 승자 없는 요소 · 통과 못한 요소가 `unresolved`에 나타난다
      → 프롬프트 재료 블록 검증: `인증: 이번 실행에서 조사하지 않음`이 들어가고
        `defer`인 `전문검색`은 들어가지 않는다
- [x] **설계 확정이 실패해도 요소별 순위가 남는다** — `finalize_design`을 일부러
      깨뜨려 확인했다. `picks`·`scores`·`designs`가 그대로 남고 `gaps`에
      `설계 확정 실패: ...`만 기록된다
- [x] 요소별 LLM 호출 수가 늘지 않았다 — 확정은 **요소 수와 무관하게 1회**다
      → `finalize_design`은 루프 밖 1곳, `judge_element`는 요소별 (코드 위치 확인)
- [x] 1위가 하나도 없으면(전 요소 후보 탈락) 확정을 부르지 않는다
      → `if not picks:` 가드 + `gaps` 기록 (코드 경로 확인)
- [x] `shape`·`data_flow`가 비면 `fill_structure`가 기본틀에서 복사하고 `gaps`에 남긴다
      → 빈 구조 입력에서 경고 2건 확인
- [x] 프롬프트 재료 5개 블록이 의도대로 조립된다 — 기본틀(구조·흐름·구축 순서·미해결) ·
      승자 + **`cons`·`caveats`**(수정의 근거) · 닫힌 결정 · 미해결.
      `designs`가 없으면 "설계 본문이 없다"로 대체된다
- [x] 문서(`03-저장.md` · `4-evaluate.md`)와 필드 9개·컬럼명이 일치한다

### 내용 품질 (E2E로 확인 — Haiku 기준)

- [x] `uv run scout run "..." --auto-approve-search` 가 완주한다 (`report.html`까지)
- [x] `scout show <slug> evaluate` 에 `final_designs` 1행이 나온다
- [x] `summary` 에 **고른 후보 이름이 실제로 들어 있다**
      → "Express + Socket.io(인메모리 어댑터)로 실시간 메시지 전달을 지원하고,
        Bull 기반 백그라운드 작업 큐로 … Prisma ORM으로 PostgreSQL에 …"
- [x] **`shape`·`data_flow`가 채워진다** — 확정 설계에 구조가 없으면 이 STEP이 성립하지 않는다
- [x] `integration_notes` 가 **두 선택이 만나는 지점**을 짚는다 (개별 후보 설명이 아니다)
      → "Socket.io와 Bull 큐 연계: … Redis 어댑터로 확장하면 워커 프로세스가
        Redis pub/sub을 거쳐 메시지를 전달해야 함"
- [x] `combination_risks` 가 `verdicts.cons`·`caveats`의 사본이 아니다
      → "단일 서버 인메모리 어댑터는 서버 재시작 시 Socket 연결 상태를 손실 —
        Redis 어댑터 마이그레이션 일정을 3개월 마일스톤에 포함해야" (조합·배포 전제의 위험)
- [x] `build_order` 가 `Architecture.build_order`를 고른 것들의 이름으로 다시 쓴 형태다
      → "Prisma 스키마 및 PostgreSQL 설정" · "Express 기본 서버 + Socket.io 인메모리 어댑터 연결"
- [~] `changes_from_design`의 각 항목이 **조사 결과를 근거로 든다** ·
      **바꿀 근거가 없으면 `Architecture`를 유지하고 변경 목록이 빈다**
      → Haiku에서 변경 목록이 **비었다**(앵커 1이 과하게 먹은 쪽). 그런데 `shape`는
        미세하게 달라졌다 — v1 `Socket.io 실시간 계층(Express + Socket.io)` →
        v2 `(… 인메모리 어댑터)`. 어댑터 명시는 후보 선정의 반영이므로 변경 목록에
        적혔어야 한다. **Sonnet에서 다시 본다** — 판단 품질 항목이다

## 막히면

**순서를 반드시 지킨다** — 요소별 `_save_pick`이 끝난 **뒤에** 확정을 부른다.
앞에 두면 확정이 실패할 때 요소별 결과까지 함께 날아간다 (불변식 11).

**`designs` 행이 없을 수 있다** — 체크포인트가 없는 slug에서 `evaluate`만 돌리는
경우다. 설계 본문 없이 요소별 승자만으로 확정하고 `gaps`에 "설계 본문 없음"을 남긴다.
예외를 던지지 않는다.

**`overall` 평균 유혹이 여기서 다시 온다** — `stack_rationale`에 점수를 다시 합산하지
않는다. 이미 매긴 `overall`과 `winner_reason`을 인용한다 (불변식 6).

**설계를 처음부터 다시 쓰고 싶은 충동을 참는다.** 이 단계는 기본틀을 **고치는** 일이고
새로 쓰는 일이 아니다. `Architecture`의 문장이 어색해 보여도 근거 없이 손대면
`changes_from_design`이 소음이 되고, 조사가 무엇을 바꿨는지 보이지 않게 된다.

**`shape`·`data_flow`가 비어서 나오면** `Architecture`의 값을 그대로 복사하고
`gaps`에 기록한다 — 확정 설계에 구조가 없는 상태로 `report`에 넘기지 않는다.

**확정을 `report`에서 하려는 충동을 참는다** — `report`는 LLM을 쓰지 않는다(불변식 7).
그 규칙을 깨면 프롬프트 튜닝에 반나절이 사라진다.
