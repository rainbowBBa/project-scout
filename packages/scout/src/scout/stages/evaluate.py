"""evaluate 단계 — 후보끼리 비교해 요소별 1위를 고른다 (stages/4-evaluate.md).

verify가 판정을 끝냈으므로 여기서는 사실을 다시 해석하지 않는다. 같은 사실을 두 번
추론하면 두 결론이 갈리고, 그러면 어느 쪽을 믿어야 할지 알 수 없다.

점수를 만드는 방식이 두 갈래다:
- maturity·risk 는 rubric.py 가 계산한다 (불변식 5 — 판정과 계산의 이중 안전망)
- overall 은 judge 가 판단한다 (불변식 6 — 평균이 아니다)

계산으로 끝나는 것은 judge에게 묻지 않는다. margin이 그 예다 — judge가 채운 값을
코드가 뺄셈으로 덮어쓴다. 요소당 LLM 1회, 통과 후보가 1개 이하면 0회다.
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

from scout import rubric, store
from scout.llm import invoke_structured
from scout.progress import step
from scout.prompts import (
    EVALUATE_MISMATCH_PROMPT,
    EVALUATE_PROMPT,
    EVALUATE_RETRY_HINT,
    FINALIZE_PROMPT,
    FINALIZE_RETRY_HINT,
)
from scout.schemas import ElementPick, FinalDesign

if TYPE_CHECKING:
    from collections.abc import Sequence

    from langchain_aws import ChatBedrockConverse

    from scout.schemas import (
        Architecture,
        Candidate,
        Component,
        Interview,
        Verdict,
    )
    from scout.state import ScoutState

# 계산된 점수 한 후보분 — (maturity, risk), 각각 (점수, 근거).
Computed = dict[str, tuple[tuple[int | None, str], tuple[int | None, str]]]

# 1위와 2위의 overall 차이가 이만큼이면 decisive다 (4-evaluate.md "margin").
_DECISIVE_GAP = 2
_WORD_RE = re.compile(r"[0-9A-Za-z가-힣]{3,}")


def _bullets(items: Sequence[str]) -> str:
    return "; ".join(items) if items else "(없음)"


def _score_line(label: str, scored: tuple[int | None, str]) -> str:
    score, reason = scored
    shown = rubric.UNAVAILABLE if score is None else str(score)
    return f"{label} {shown} ({reason})"


def _candidates_block(
    passing: Sequence[Verdict],
    by_name: dict[str, Candidate],
    computed: Computed,
) -> str:
    blocks = []
    for verdict in passing:
        candidate = by_name.get(verdict.candidate)
        maturity, risk = computed[verdict.candidate]
        blocks.append(
            "\n".join(
                [
                    f"[{verdict.candidate}] ({candidate.kind if candidate else 'unknown'})",
                    f"  무엇인가: {candidate.what_it_is if candidate else '(정보 없음)'}",
                    f"  판정: 해결함 · confidence {verdict.confidence}",
                    f"  판정 이유: {verdict.solves_reason}",
                    f"  장점: {_bullets(verdict.pros)}",
                    f"  단점: {_bullets(verdict.cons)}",
                    f"  유의: {_bullets(verdict.caveats)}",
                    f"  인용한 사실: {', '.join(verdict.citations) or '(없음)'}",
                    f"  {_score_line('계산된 maturity', maturity)}",
                    f"  {_score_line('계산된 risk', risk)}",
                ]
            )
        )
    return "\n\n".join(blocks)


def _prompt_input(
    component_name: str,
    component: Component | None,
    interview: Interview,
    candidates_block: str,
) -> dict[str, str]:
    return {
        "component_name": component_name,
        "component_why": component.role_in_design if component else "(요소 정보 없음)",
        "approach_notes": component.approach_notes if component else "(없음)",
        "refined_brief": interview.refined_brief,
        "assumptions": "\n".join(f"- {a}" for a in interview.assumptions) or "(없음)",
        "candidates_block": candidates_block,
    }


def judge_element(
    llm: ChatBedrockConverse,
    component_name: str,
    component: Component | None,
    interview: Interview,
    passing: Sequence[Verdict],
    by_name: dict[str, Candidate],
    computed: Computed,
) -> ElementPick:
    """요소 하나의 통과 후보 전체를 놓고 overall과 순위를 받는다 — 동기 blocking 호출.

    winner와 ranking[0]이 어긋나면 어느 쪽이 judge의 판단인지 알 수 없으므로 1회
    되묻는다. 코드가 임의로 고르면 winner_reason이 다른 후보를 가리킨 채로 남는다.
    """
    prompt_input = _prompt_input(
        component_name,
        component,
        interview,
        _candidates_block(passing, by_name, computed),
    )
    structured_llm = llm.with_structured_output(ElementPick, include_raw=True)

    pick, raw = invoke_structured(
        EVALUATE_PROMPT,
        structured_llm,
        prompt_input,
        EVALUATE_RETRY_HINT,
        schema=ElementPick,
    )
    if pick is None:
        raise RuntimeError(f"ElementPick 구조화 출력 파싱 실패: {raw}")

    if pick.ranking and pick.winner != pick.ranking[0]:
        retry, _ = invoke_structured(
            EVALUATE_MISMATCH_PROMPT,
            structured_llm,
            {
                **prompt_input,
                "mismatch": f"winner={pick.winner} / ranking[0]={pick.ranking[0]}",
            },
            EVALUATE_RETRY_HINT,
            schema=ElementPick,
        )
        if retry is not None:
            pick = retry

    return pick


def normalize(
    pick: ElementPick,
    component_name: str,
    passing_names: Sequence[str],
    computed: Computed,
) -> tuple[ElementPick, list[str]]:
    """judge의 출력을 데이터에 맞춘다 — 순위 재정렬 · winner 확정 · margin 계산.

    ranking은 overall 내림차순이 진실이므로 코드가 다시 정렬하고 winner를 그 첫 번째로
    확정한다. margin은 뺄셈이라 judge가 채운 값을 그대로 덮어쓴다.
    """
    warnings: list[str] = []
    allowed = set(passing_names)

    scores = []
    seen: set[str] = set()
    for score in pick.scores:
        if score.candidate not in allowed:
            warnings.append(
                f"'{component_name}': 통과 목록에 없는 후보 "
                f"'{score.candidate}'를 채점해 제외했다"
            )
            continue
        if score.candidate in seen:
            continue
        seen.add(score.candidate)
        scores.append(
            score.model_copy(update={"overall": max(1, min(5, score.overall))})
        )

    missing = [name for name in passing_names if name not in seen]
    if missing:
        warnings.append(
            f"'{component_name}': 채점에서 빠진 통과 후보 {', '.join(missing)} — "
            "overall 없이 순위 끝에 둔다"
        )

    overall_by_name = {s.candidate: s.overall for s in scores}

    def sort_key(candidate: str) -> tuple[int, int, str]:
        # 동점은 maturity가 높은 쪽이 앞선다. unavailable(None)은 0으로 최하위가 된다.
        maturity = computed[candidate][0][0] or 0
        return (-overall_by_name.get(candidate, 0), -maturity, candidate)

    ranking = sorted(passing_names, key=sort_key)
    scores.sort(key=lambda s: ranking.index(s.candidate))

    top = [overall_by_name.get(name, 0) for name in ranking[:2]]
    margin = "decisive" if len(top) < 2 or top[0] - top[1] >= _DECISIVE_GAP else "close"

    if pick.winner != ranking[0]:
        warnings.append(
            f"'{component_name}': winner '{pick.winner}'가 순위 1위 "
            f"'{ranking[0]}'와 달라 순위를 따랐다"
        )

    return (
        pick.model_copy(
            update={
                "component": component_name,
                "scores": scores,
                "ranking": ranking,
                "winner": ranking[0],
                "margin": margin,
            }
        ),
        warnings,
    )


def _is_average(
    overall: int, scored: tuple[tuple[int | None, str], tuple[int | None, str]]
) -> bool:
    maturity, risk = scored[0][0], scored[1][0]
    if maturity is None or risk is None:
        return False
    return overall == round((maturity + risk) / 2)


def audit(
    pick: ElementPick,
    component_name: str,
    refined_brief: str,
    computed: Computed,
) -> list[str]:
    """프롬프트가 먹혔는지 검사한다 — 통과시키되 경고를 남긴다 (4-evaluate.md "실패 처리")."""
    warnings = []
    brief_words = {w.lower() for w in _WORD_RE.findall(refined_brief)}

    if not any(w.lower() in brief_words for w in _WORD_RE.findall(pick.winner_reason)):
        warnings.append(
            f"'{component_name}': winner_reason에 제약 인용이 보이지 않는다"
        )
    if not re.search(r"\d", pick.winner_reason):
        warnings.append(f"'{component_name}': winner_reason에 2위와의 점수 차이가 없다")

    # 한 후보가 우연히 평균과 같을 수는 있다. 전원이 그러면 반례가 안 먹힌 것이다 (불변식 6).
    averaged = [s for s in pick.scores if _is_average(s.overall, computed[s.candidate])]
    if len(pick.scores) >= 2 and len(averaged) == len(pick.scores):
        warnings.append(
            f"'{component_name}': overall이 전부 maturity·risk의 평균과 같다 — "
            "프롬프트 반례가 먹히지 않았을 수 있다"
        )
    return warnings


def solo_pick(component_name: str, verdict: Verdict) -> ElementPick:
    """통과 후보가 하나면 비교할 대상이 없다 — LLM을 부르지 않는다."""
    return ElementPick(
        component=component_name,
        scores=[],
        ranking=[verdict.candidate],
        winner=verdict.candidate,
        winner_reason=f"통과한 후보가 이것뿐이다. 판정 이유: {verdict.solves_reason}",
        runner_up_note="비교할 2위가 없다 — 다른 후보는 모두 탈락했다.",
        margin="decisive",
    )


def store_computed_scores(
    slug: str, candidates: Sequence[Candidate], *, runs_dir: str | None = None
) -> Computed:
    """전 후보의 maturity·risk를 계산해 저장한다 — 탈락 후보도 포함한다.

    탈락 후보를 빼면 "judge는 통과시켰지만 계산은 1을 줬다"를 보고서에서 보여줄 수 없고,
    이중 안전망이 작동한 증거가 사라진다.
    """
    computed: Computed = {}
    for candidate in candidates:
        maturity = rubric.maturity(candidate.dossier)
        risk = rubric.risk(candidate.dossier)
        computed[candidate.name] = (maturity, risk)
        for criterion, (score, reason) in (("maturity", maturity), ("risk", risk)):
            store.set_score(
                slug,
                candidate.name,
                criterion,
                score,
                rubric.COMPUTED if score is not None else rubric.UNAVAILABLE,
                reason,
                runs_dir=runs_dir,
            )
    return computed


def _save_pick(
    slug: str, pick: ElementPick, *, judged: bool, runs_dir: str | None = None
) -> None:
    for index, name in enumerate(pick.ranking):
        first = index == 0
        store.add_pick(
            slug,
            pick.component,
            name,
            rank=index + 1,
            winner_reason=pick.winner_reason if first else None,
            runner_up_note=pick.runner_up_note if first else None,
            margin=pick.margin if first else None,
            runs_dir=runs_dir,
        )

    scored = {s.candidate: s for s in pick.scores}
    for name in pick.ranking:
        score = scored.get(name)
        if score is None:
            # 후보가 하나뿐이라 judge를 부르지 않았거나, judge가 채점에서 빠뜨렸다.
            # 0을 넣지 않고 없다고 적는다 (불변식 12).
            reason = (
                "judge가 이 후보를 채점하지 않았다"
                if judged
                else "통과 후보가 하나뿐이라 비교 없이 1위 — overall을 매기지 않았다"
            )
            store.set_score(
                slug,
                name,
                "overall",
                None,
                rubric.UNAVAILABLE,
                reason,
                runs_dir=runs_dir,
            )
            continue
        store.set_score(
            slug,
            name,
            "overall",
            score.overall,
            "judged",
            score.score_reason,
            runs_dir=runs_dir,
        )


async def _evaluate_component(
    slug: str,
    component_name: str,
    component: Component | None,
    verdicts: Sequence[Verdict],
    by_name: dict[str, Candidate],
    computed: Computed,
    interview: Interview,
    llm: ChatBedrockConverse,
    semaphore: asyncio.Semaphore,
    *,
    runs_dir: str | None = None,
) -> tuple[ElementPick | None, list[str]]:
    """요소 하나: 탈락 기록 → judge → 교정 → 저장. LLM 호출만 스레드로 뺀다.

    store 접근을 이벤트 루프 스레드에 남겨두면 요소를 병렬로 돌려도 sqlite 쓰기가
    저절로 직렬화된다 (verify와 같은 이유).
    """
    store.clear_picks(slug, component_name, runs_dir=runs_dir)

    passing = [v for v in verdicts if v.solves_it]
    for verdict in (v for v in verdicts if not v.solves_it):
        # 탈락 사유는 judge가 이미 근거와 함께 썼다 — 새로 만들지 않고 그대로 인용한다.
        store.add_pick(
            slug,
            component_name,
            verdict.candidate,
            rejected_reason=verdict.solves_reason,
            runs_dir=runs_dir,
        )

    if not passing:
        gap = f"'{component_name}': 통과 후보가 없다 — 전 후보 탈락"
        store.add_gap(slug, component_name, gap, runs_dir=runs_dir)
        return None, [gap]

    if len(passing) == 1:
        step("통과 후보 1개 — 비교 없이 1위", subject=component_name)
        pick = solo_pick(component_name, passing[0])
        _save_pick(slug, pick, judged=False, runs_dir=runs_dir)
        return pick, []

    step(f"채점 (통과 후보 {len(passing)})", subject=component_name)
    async with semaphore:
        pick = await asyncio.to_thread(
            judge_element,
            llm,
            component_name,
            component,
            interview,
            passing,
            by_name,
            computed,
        )

    pick, warnings = normalize(
        pick, component_name, [v.candidate for v in passing], computed
    )
    warnings += audit(pick, component_name, interview.refined_brief, computed)
    _save_pick(slug, pick, judged=True, runs_dir=runs_dir)
    for warning in warnings:
        store.add_gap(slug, component_name, warning, runs_dir=runs_dir)
    return pick, warnings


async def _run_evaluate(
    slug: str,
    candidates: Sequence[Candidate],
    components: Sequence[Component],
    verdicts: Sequence[Verdict],
    interview: Interview,
    computed: Computed,
    llm: ChatBedrockConverse,
    concurrency: int,
    *,
    runs_dir: str | None = None,
) -> tuple[list[ElementPick], list[str]]:
    by_name = {c.name: c for c in candidates}
    component_by_name = {c.name: c for c in components}
    semaphore = asyncio.Semaphore(concurrency)

    grouped: dict[str, list[Verdict]] = {}
    for verdict in verdicts:
        grouped.setdefault(verdict.component, []).append(verdict)

    names = list(grouped)
    results = await asyncio.gather(
        *(
            _evaluate_component(
                slug,
                name,
                component_by_name.get(name),
                grouped[name],
                by_name,
                computed,
                interview,
                llm,
                semaphore,
                runs_dir=runs_dir,
            )
            for name in names
        ),
        return_exceptions=True,
    )

    picks: list[ElementPick] = []
    gaps: list[str] = []
    for name, result in zip(names, results, strict=True):
        if isinstance(result, BaseException):
            # 요소 하나가 죽어도 나머지 요소는 계속 간다 (불변식 11).
            gap = f"'{name}' 평가 실패: {result}"
            store.add_gap(slug, name, gap, runs_dir=runs_dir)
            gaps.append(gap)
            continue
        pick, warnings = result
        gaps.extend(warnings)
        if pick is not None:
            picks.append(pick)
    return picks, gaps


# ── 설계 확정 ────────────────────────────────────────────────────────────


def _architecture_block(architecture: Architecture | None) -> str:
    if architecture is None:
        return "(설계 본문이 없다 — 요소별 승자만으로 확정해라)"
    order = " → ".join(architecture.build_order) or "(없음)"
    return "\n".join(
        [
            f"요약: {architecture.summary}",
            f"구조(shape): {architecture.shape}",
            f"데이터 흐름(data_flow): {architecture.data_flow}",
            f"구축 순서: {order}",
            f"미해결 질문: {_bullets(architecture.open_questions)}",
        ]
    )


def _picks_block(
    picks: Sequence[ElementPick], verdict_by_name: dict[str, Verdict]
) -> str:
    blocks = []
    for pick in picks:
        lines = [
            f"[{pick.component}] → {pick.winner} (margin {pick.margin})",
            f"  고른 이유: {pick.winner_reason}",
            f"  2위: {pick.runner_up_note}",
        ]
        verdict = verdict_by_name.get(pick.winner)
        if verdict:
            # 구조 전제를 깨뜨리는 게 있는지 — shape·data_flow 수정의 근거다
            lines.append(f"  단점: {_bullets(verdict.cons)}")
            lines.append(f"  유의: {_bullets(verdict.caveats)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) or "(고른 것이 없다)"


def _closed_block(components: Sequence[Component]) -> str:
    closed = [
        f"- {c.name}: {c.no_comparison_reason or '(이유 없음)'}"
        for c in components
        if not c.needs_comparison
    ]
    return "\n".join(closed) or "(없음)"


def _unresolved_block(
    components: Sequence[Component], covered: set[str], verdicts: Sequence[Verdict]
) -> str:
    lines = []
    for component in components:
        if not component.needs_comparison or component.name in covered:
            continue
        if component.necessity in ("defer", "unnecessary"):
            continue
        judged = any(v.component == component.name for v in verdicts)
        why = "전 후보 탈락" if judged else "이번 실행에서 조사하지 않음"
        lines.append(f"- {component.name}: {why}")
    return "\n".join(lines) or "(없음)"


def finalize_design(
    llm: ChatBedrockConverse,
    architecture: Architecture | None,
    picks: Sequence[ElementPick],
    components: Sequence[Component],
    verdicts: Sequence[Verdict],
    interview: Interview,
) -> FinalDesign:
    """기본틀을 조사 결과로 수정해 확정한다 — LLM 1회, 요소 수와 무관하다.

    후보를 다시 비교하지 않는다. 요소별 판단(`winner_reason`)은 인용하고, 판단하는
    것은 **조합**이다 (4-evaluate.md "확정 설계는 기본틀의 수정판이다").
    """
    prompt_input = {
        "refined_brief": interview.refined_brief,
        "architecture_block": _architecture_block(architecture),
        "picks_block": _picks_block(picks, {v.candidate: v for v in verdicts}),
        "closed_block": _closed_block(components),
        "unresolved_block": _unresolved_block(
            components, {p.component for p in picks}, verdicts
        ),
    }
    final, raw = invoke_structured(
        FINALIZE_PROMPT,
        llm.with_structured_output(FinalDesign, include_raw=True),
        prompt_input,
        FINALIZE_RETRY_HINT,
        schema=FinalDesign,
    )
    if final is None:
        raise RuntimeError(f"FinalDesign 구조화 출력 파싱 실패: {raw}")
    return final


def fill_structure(
    final: FinalDesign, architecture: Architecture | None
) -> tuple[FinalDesign, list[str]]:
    """확정 설계에 구조가 없으면 기본틀에서 복사한다.

    구조 없는 확정 설계를 `report`에 넘기면 최상단 섹션이 비고 "수정 설계 완성"이
    성립하지 않는다. 채우되 조용히 넘기지 않고 `gaps`에 남긴다.
    """
    warnings: list[str] = []
    update: dict[str, str] = {}
    for field in ("shape", "data_flow"):
        if getattr(final, field).strip():
            continue
        if architecture is None:
            warnings.append(f"확정 설계의 {field}가 비었고 기본틀도 없다")
            continue
        update[field] = getattr(architecture, field)
        warnings.append(f"확정 설계의 {field}가 비어 기본틀 값을 그대로 썼다")
    return (final.model_copy(update=update) if update else final), warnings


def evaluate_node(state: ScoutState, *, llm: ChatBedrockConverse) -> dict:
    from scout.config import Settings

    slug = state["slug"]
    # state가 비면 저장된 값으로 돈다 — `--from evaluate`로 프롬프트만 고쳐 다시 돌릴 때
    # 앞 단계를 다시 태우지 않기 위해서다.
    candidates = state.get("candidates") or store.get_candidates(slug)
    verdicts = state.get("verdicts") or store.get_verdicts(slug)
    if not verdicts:
        store.add_gap(slug, "evaluate", "판정이 없어 순위 산정을 건너뜀")
        return {"element_picks": []}

    # 계산은 judge와 무관하게 전 후보에 대해 먼저 끝낸다 — 판정이 실패한 요소에서도
    # 계산된 점수는 남는다 (이중 안전망의 한쪽).
    step(f"계산 점수 {len(candidates)}개 후보")
    computed = store_computed_scores(slug, candidates)

    components = state.get("components") or store.get_components(slug)
    settings = Settings()
    picks, _ = asyncio.run(
        _run_evaluate(
            slug,
            candidates,
            components,
            verdicts,
            state["interview"],
            computed,
            llm,
            settings.scout_llm_concurrency,
        )
    )

    # ★ 확정은 요소별 픽이 **저장된 뒤**에 돈다 — 앞에 두면 확정이 실패할 때
    # 요소별 결과까지 함께 날아간다 (불변식 11).
    if not picks:
        store.add_gap(slug, "evaluate", "1위가 없어 설계 확정을 건너뜀")
        return {"element_picks": picks}

    architecture = state.get("architecture") or store.get_design(slug)
    if architecture is None:
        store.add_gap(slug, "evaluate", "설계 본문 없음 — 요소별 승자만으로 확정한다")
    step("설계 확정")
    try:
        final = finalize_design(
            llm, architecture, picks, components, verdicts, state["interview"]
        )
    except Exception as e:  # noqa: BLE001 — 확정 실패가 요소별 순위를 무르지 않는다
        store.add_gap(slug, "evaluate", f"설계 확정 실패: {e}")
        return {"element_picks": picks}

    final, warnings = fill_structure(final, architecture)
    store.upsert_final_design(slug, final)
    for warning in warnings:
        store.add_gap(slug, "evaluate", warning)

    return {"element_picks": picks, "final_design": final}
