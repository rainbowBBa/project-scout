"""verify 단계 — 후보를 하나씩 독립 판정(pointwise)하고, judge의 인용이 dossier에
실제로 있는지 코드가 SQL로 대조한다. 이 프로젝트의 중심 단계다.

후보당 LLM 1회 (3-verify.md). 후보를 나란히 놓고 한 번에 판정하지 않는 이유는 제시
순서가 결과를 바꾸기 때문이다 — 후보 간 상대 비교는 evaluate가 맡는다. 판정과 비교를
분리한다.

grounding 위반이 나온 후보만 위반 목록을 붙여 1회 더 판정하고, 2차에도 남으면
confidence를 강등한다 (절단선 3번은 이 재판정 루프까지다 — 검출 자체는 절단하지
않는다).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from scout import grounding, store
from scout.llm import invoke_structured
from scout.prompts import (
    VERIFY_PROMPT,
    VERIFY_REGROUND_PROMPT,
    VERIFY_RETRY_HINT,
)
from scout.schemas import Verdict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from langchain_aws import ChatBedrockConverse

    from scout.schemas import Candidate, Component, Interview
    from scout.state import ScoutState

_MAX_REGROUND = 1


def _dossier_block(candidate: Candidate) -> str:
    if not candidate.dossier:
        return "(없음 — 인용할 수 있는 사실이 하나도 없다)"
    return "\n".join(f"- {f.id} | {f.label}: {f.value}" for f in candidate.dossier)


def _build_prompt_input(
    candidate: Candidate, component: Component | None, interview: Interview
) -> dict[str, str]:
    return {
        "candidate_name": candidate.name,
        "candidate_kind": candidate.kind,
        "what_it_is": candidate.what_it_is,
        "component_name": candidate.component,
        "component_why": component.role_in_design if component else "(요소 정보 없음)",
        "approach_notes": component.approach_notes if component else "(없음)",
        "refined_brief": interview.refined_brief,
        "assumptions": "\n".join(f"- {a}" for a in interview.assumptions) or "(없음)",
        "dossier": _dossier_block(candidate),
        "dossier_gaps": "\n".join(f"- {g}" for g in candidate.dossier_gaps) or "(없음)",
    }


def judge_candidate(
    llm: ChatBedrockConverse,
    candidate: Candidate,
    component: Component | None,
    interview: Interview,
    *,
    violations: list[str] | None = None,
) -> Verdict:
    """후보 하나를 판정한다 — 동기 blocking 호출. 툴도 멀티턴도 없다.

    `violations`가 있으면 재판정이다. 실패 시 RuntimeError를 던지고, 후보 단위 처리는
    호출부가 맡는다 (불변식 11 — 후보 하나가 전체를 죽이지 않는다).
    """
    prompt_input = _build_prompt_input(candidate, component, interview)
    prompt = VERIFY_PROMPT
    if violations:
        prompt = VERIFY_REGROUND_PROMPT
        prompt_input = {
            **prompt_input,
            "violations": "\n".join(f"- {v}" for v in violations),
        }

    structured_llm = llm.with_structured_output(Verdict, include_raw=True)
    verdict, raw = invoke_structured(
        prompt, structured_llm, prompt_input, VERIFY_RETRY_HINT
    )
    if verdict is None:
        raise RuntimeError(f"Verdict 구조화 출력 파싱 실패: {raw}")

    # 이름은 코드가 확정한다 — judge가 후보명을 조금이라도 바꾸면 verdicts 행이
    # candidates·facts와 조인되지 않아 grounding 대조 자체가 무력해진다.
    return verdict.model_copy(
        update={"candidate": candidate.name, "component": candidate.component}
    )


def failed_verdict(candidate: Candidate, reason: str) -> Verdict:
    """판정이 끝내 실패한 후보의 자리를 채운다 — 빠뜨리지 않고 실패를 기록한다."""
    return Verdict(
        candidate=candidate.name,
        component=candidate.component,
        solves_it=False,
        solves_reason=f"판정 실패: {reason}",
        pros=[],
        cons=[],
        caveats=[],
        confidence="low",
        citations=[],
        unsupported_claims=[],
    )


async def _verify_candidate(
    slug: str,
    candidate: Candidate,
    component: Component | None,
    interview: Interview,
    llm: ChatBedrockConverse,
    semaphore: asyncio.Semaphore,
    *,
    runs_dir: str | None = None,
) -> Verdict:
    """판정 → 저장 → grounding 대조 → (위반이면) 재판정 → 2차 위반이면 강등.

    LLM 호출만 스레드로 뺀다. store 접근을 이벤트 루프 스레드에 남겨두면 후보를
    병렬로 돌려도 sqlite 쓰기가 저절로 직렬화된다.
    """
    violations: list[str] | None = None
    recorded_violations = 0
    verdict = failed_verdict(candidate, "판정을 시작하지 못함")
    for attempt in range(_MAX_REGROUND + 1):
        async with semaphore:
            verdict = await asyncio.to_thread(
                judge_candidate,
                llm,
                candidate,
                component,
                interview,
                violations=violations,
            )
        store.upsert_verdict(slug, verdict, runs_dir=runs_dir)

        violations = grounding.ungrounded(slug, candidate.name, runs_dir=runs_dir)
        if not violations:
            break
        if attempt == _MAX_REGROUND:
            # 2차에도 위반 — 더 묻지 않고 강등한다 (3-verify.md "실패 처리").
            recorded_violations = len(violations)
            verdict = grounding.force_low(
                grounding.strip_ungrounded(verdict, violations)
            )
            store.upsert_verdict(
                slug,
                verdict,
                grounding_violations=recorded_violations,
                runs_dir=runs_dir,
            )
            store.add_gap(
                slug,
                candidate.name,
                f"grounding 위반 {len(violations)}건 — dossier에 없는 인용: "
                f"{', '.join(violations)}",
            )

    degraded = grounding.degrade_if_uncited(verdict)
    if degraded is not verdict:
        # grounding_violations를 다시 넘긴다 — 기본값으로 upsert하면 방금 기록한
        # 위반 횟수가 0으로 덮인다 (인용을 전부 걷어낸 판정이 바로 이 경우다).
        store.upsert_verdict(
            slug, degraded, grounding_violations=recorded_violations, runs_dir=runs_dir
        )
        store.add_gap(slug, candidate.name, "인용 없는 판정 — confidence 강등")
        verdict = degraded
    return verdict


async def _run_verify(
    slug: str,
    candidates: Sequence[Candidate],
    components: Sequence[Component],
    interview: Interview,
    llm: ChatBedrockConverse,
    concurrency: int,
    *,
    runs_dir: str | None = None,
) -> tuple[list[Verdict], list[str]]:
    by_name = {c.name: c for c in components}
    semaphore = asyncio.Semaphore(concurrency)

    results = await asyncio.gather(
        *(
            _verify_candidate(
                slug,
                candidate,
                by_name.get(candidate.component),
                interview,
                llm,
                semaphore,
                runs_dir=runs_dir,
            )
            for candidate in candidates
        ),
        return_exceptions=True,
    )

    verdicts: list[Verdict] = []
    gaps: list[str] = []
    for candidate, result in zip(candidates, results, strict=True):
        if isinstance(result, BaseException):
            # 후보 하나가 죽어도 나머지는 계속 간다 (불변식 11)
            verdict = failed_verdict(candidate, str(result))
            store.upsert_verdict(slug, verdict, runs_dir=runs_dir)
            store.add_gap(slug, candidate.name, f"판정 실패: {result}")
            gaps.append(f"'{candidate.name}' 판정 실패: {result}")
            verdicts.append(verdict)
            continue
        verdicts.append(result)
    return verdicts, gaps


def verify_node(state: ScoutState, *, llm: ChatBedrockConverse) -> dict:
    from scout.config import Settings

    slug = state["slug"]
    # state가 비면 저장된 후보로 돈다 — `--from verify`로 프롬프트만 고쳐 다시 돌릴 때
    # search를 다시 태우지 않기 위해서다.
    candidates = state.get("candidates") or store.get_candidates(slug)
    if not candidates:
        store.add_gap(slug, "verify", "판정할 후보가 없어 검증을 건너뜀")
        return {"verdicts": []}

    settings = Settings()
    verdicts, gaps = asyncio.run(
        _run_verify(
            slug,
            candidates,
            state.get("components") or store.get_components(slug),
            state["interview"],
            llm,
            settings.scout_llm_concurrency,
        )
    )
    for gap in gaps:
        store.add_gap(slug, "verify", gap)

    return {"verdicts": verdicts}
