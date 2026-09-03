"""report 단계 — scout.db를 jinja2로 단일 HTML로 렌더링한다 (stages/5-report.md).

LLM을 쓰지 않는다 (불변식 7) — evaluate까지 끝낸 구조화된 결과를 SQL로 모아 템플릿에
꽂기만 한다. 요약 문장이 필요한 자리는 judge가 이미 쓴 문장(`solves_reason`,
`winner_reason` 등)을 그대로 인용한다.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

import jinja2

from scout import store

if TYPE_CHECKING:
    from scout.state import ScoutState

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_PASSING_NECESSITY = {"essential", "valuable"}
_DEFERRED_NECESSITY = {"defer", "unnecessary"}


def _env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def build_report_context(slug: str, *, runs_dir: str | None = None) -> dict:
    """store 전체를 읽어 템플릿이 바로 쓸 수 있는 dict로 조립한다.

    여기서는 SQL 조인·그룹핑만 한다 — verify·evaluate가 이미 끝낸 판단·계산을
    다시 해석하지 않는다.
    """
    run = store.get_run(slug, runs_dir=runs_dir) or {}
    interview = run.get("interview") or {}
    components = store.get_components(slug, runs_dir=runs_dir)
    candidates = store.get_candidates(slug, runs_dir=runs_dir)
    verdicts = store.get_verdicts(slug, runs_dir=runs_dir)
    scores = store.get_scores(slug, runs_dir=runs_dir)
    picks = store.get_picks(slug, runs_dir=runs_dir)
    violations = store.get_grounding_violations(slug, runs_dir=runs_dir)
    all_gaps = store.get_all_gaps(slug, runs_dir=runs_dir)
    # 설계 두 버전 — designs(v1, 조사 전)와 final_designs(v2, 확정).
    # 같은 이름의 shape·data_flow를 나란히 놓는 것이 곧 대조표다 (03-저장.md).
    architecture = store.get_design(slug, runs_dir=runs_dir)
    final_design = store.get_final_design(slug, runs_dir=runs_dir)

    candidate_by_key = {(c.component, c.name): c for c in candidates}
    verdict_by_name = {v.candidate: v for v in verdicts}

    scores_by_candidate: dict[str, dict[str, dict]] = defaultdict(dict)
    for s in scores:
        scores_by_candidate[s["candidate"]][s["criterion"]] = s

    picks_by_component: dict[str, list[dict]] = defaultdict(list)
    for p in picks:
        picks_by_component[p["component"]].append(p)

    covered = set(picks_by_component)
    passing_names = {
        c.name
        for c in components
        if c.necessity in _PASSING_NECESSITY and c.needs_comparison
    }

    stack: list[dict] = []
    no_winner: list[str] = []
    elements: list[dict] = []

    for component in components:
        if component.name not in covered:
            continue

        rows = sorted(
            picks_by_component[component.name],
            key=lambda p: (p["rank"] is None, p["rank"] or 0),
        )
        candidate_rows = []
        winner_row = None
        for row in rows:
            candidate = candidate_by_key.get((component.name, row["candidate"]))
            if row["rank"] == 1:
                winner_row = row
            candidate_scores = scores_by_candidate.get(row["candidate"], {})
            candidate_rows.append(
                {
                    "name": row["candidate"],
                    "kind": candidate.kind if candidate else None,
                    "what_it_is": candidate.what_it_is if candidate else "",
                    "rank": row["rank"],
                    "rejected_reason": row["rejected_reason"],
                    "winner_reason": row["winner_reason"],
                    "runner_up_note": row["runner_up_note"],
                    "margin": row["margin"],
                    "verdict": verdict_by_name.get(row["candidate"]),
                    "overall": candidate_scores.get("overall"),
                    "maturity": candidate_scores.get("maturity"),
                    "risk": candidate_scores.get("risk"),
                    "dossier_gaps": candidate.dossier_gaps if candidate else [],
                    "grounding_violations": violations.get(row["candidate"], 0),
                }
            )

        elements.append({"component": component, "candidates": candidate_rows})

        if winner_row is not None:
            candidate_name = winner_row["candidate"]
            stack.append(
                {
                    "component": component.name,
                    "candidate": candidate_name,
                    "overall": scores_by_candidate.get(candidate_name, {}).get(
                        "overall"
                    ),
                    "margin": winner_row["margin"],
                    "winner_reason": winner_row["winner_reason"],
                    "verdict": verdict_by_name.get(candidate_name),
                }
            )
        else:
            no_winner.append(component.name)

    deferred = [c for c in components if c.necessity in _DEFERRED_NECESSITY]
    # "필요 없어서"와 "이미 정해져서"는 다른 섹션이다 — 합치면 사용자가 설계의
    # 전제를 못 본다 (5-report.md 4번 · 불변식 17).
    closed = [
        c
        for c in components
        if not c.needs_comparison and c.necessity not in _DEFERRED_NECESSITY
    ]
    skipped = [
        c for c in components if c.name in passing_names and c.name not in covered
    ]

    risks: list[str] = []
    for row in stack:
        verdict = row["verdict"]
        if verdict:
            risks.extend(verdict.cons)
            risks.extend(verdict.caveats)
    risks = risks[:3]

    rejections = [
        {
            "component": p["component"],
            "candidate": p["candidate"],
            "reason": p["rejected_reason"],
        }
        for p in picks
        if p["rank"] is None
    ]

    facts_by_candidate = [
        {
            "candidate": c.name,
            "component": c.component,
            "kind": c.kind,
            "verdict": verdict_by_name.get(c.name),
            "grounding_violations": violations.get(c.name, 0),
            "facts": [
                {
                    "fact": f,
                    "cited": bool(verdict_by_name.get(c.name))
                    and f.id in verdict_by_name[c.name].citations,
                }
                for f in c.dossier
            ],
            "dossier_gaps": c.dossier_gaps,
        }
        for c in candidates
    ]

    other_gaps = [
        g for g in all_gaps if g["candidate"] not in {c.name for c in candidates}
    ]

    return {
        "slug": slug,
        "description": run.get("description", ""),
        "architecture": architecture,
        "final_design": final_design,
        "closed": closed,
        "refined_brief": interview.get("refined_brief", ""),
        "assumptions": interview.get("assumptions") or [],
        "stack": stack,
        "no_winner": no_winner,
        "risks": risks,
        "deferred": deferred,
        "skipped": skipped,
        "skipped_reopen_count": len(passing_names),
        "elements": elements,
        "rejections": rejections,
        "facts_by_candidate": facts_by_candidate,
        "other_gaps": other_gaps,
        "grounding_violations_total": sum(violations.values()),
        "rejected_count": len(rejections),
        "filtered_count": len(deferred) + len(skipped),
        "incomplete": not components or not picks,
    }


def render_report(ctx: dict) -> str:
    template = _env().get_template("report.html.j2")
    return template.render(**ctx)


def _summary(ctx: dict) -> dict:
    return {
        "stack": [
            {
                "component": row["component"],
                "candidate": row["candidate"],
                "overall": (row["overall"] or {}).get("score"),
                "margin": row["margin"],
            }
            for row in ctx["stack"]
        ],
        "filtered_count": ctx["filtered_count"],
        "rejected_count": ctx["rejected_count"],
        "grounding_violations_total": ctx["grounding_violations_total"],
    }


def report_node(state: ScoutState, *, runs_dir: str | None = None) -> dict:
    from scout.config import Settings

    slug = state["slug"]
    ctx = build_report_context(slug, runs_dir=runs_dir)
    html = render_report(ctx)

    base = runs_dir or Settings().scout_runs_dir
    path = Path(base) / slug / "report.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")

    return {"report_path": str(path), "report_summary": _summary(ctx)}
