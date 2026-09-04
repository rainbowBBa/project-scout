"""report 단계 — scout.db를 jinja2로 단일 HTML로 렌더링한다 (stages/5-report.md).

LLM을 쓰지 않는다 (불변식 7) — evaluate까지 끝낸 구조화된 결과를 SQL로 모아 템플릿에
꽂기만 한다. 요약 문장이 필요한 자리는 judge가 이미 쓴 문장(`solves_reason`,
`winner_reason` 등)을 그대로 인용한다.

`sentences` 필터가 그 인용을 문단으로 끊는다. 문장을 고치지도 줄이지도 않는다 —
경계에서 자르기만 하는 순수 함수다. judge의 문장은 실측에서 한 문단이 630자였고
저장된 값에 줄바꿈이 하나도 없어서, 끊어주지 않으면 화면이 글자 벽이 된다.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

import jinja2
from markupsafe import Markup, escape

from scout import store

if TYPE_CHECKING:
    from scout.state import ScoutState

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_PASSING_NECESSITY = {"essential", "valuable"}
_DEFERRED_NECESSITY = {"defer", "unnecessary"}

# 문장 끝 뒤의 공백에서만 끊는다.
#   `(?<=[다요](?:\.|\. ))` 로 한국어 종결을 우선 잡고, 그 밖의 `.!?`는 **뒤에 오는 것이
#   숫자가 아닐 때만** 끊는다 — 그래야 `4.17.11`·`$200. 5`·`vs.` 에서 안 잘린다.
_SENTENCE_END = re.compile(r"(?<=[다요][.!?])\s+|(?<=[.!?])\s+(?=[가-힣A-Z(\[])")
# LLM이 줄바꿈을 넣어주면 그게 문단 경계다 (지금은 안 넣지만 오면 존중한다).
_PARAGRAPH = re.compile(r"\n\s*\n|\n")


def split_sentences(text: str) -> list[str]:
    """문단으로 끊을 조각들. 빈 조각은 버린다.

    template에서 부르지 말고 `sentences` 필터를 쓴다 — 이 함수는 테스트가 경계 규칙을
    직접 검사하기 위해 열려 있다.
    """
    chunks: list[str] = []
    for block in _PARAGRAPH.split(text or ""):
        chunks.extend(part.strip() for part in _SENTENCE_END.split(block))
    return [c for c in chunks if c]


# `<summary>`에 넣을 길이. 실측에서 judge의 **첫 문장 자체가 313자**인 경우가 있었다 —
# 문장을 중간에서 끊는 건 고치는 것이므로, 접힌 전문은 그대로 두고 요약 줄만 자른다.
_SUMMARY_CHARS = 90


def _summary_line(text: str) -> str:
    """접힌 블록의 `<summary>` 한 줄. 전문은 바로 아래에 있으므로 감추는 게 아니다."""
    first = (split_sentences(text) or [""])[0]
    if len(first) <= _SUMMARY_CHARS:
        return first
    return first[:_SUMMARY_CHARS].rstrip() + "…"


def _sentences(text: str) -> Markup:
    """긴 인용을 `<p>` 묶음으로. `autoescape=True`라 조각마다 직접 이스케이프한다.

    호출부를 `<p>`로 감싸면 안 된다 — 중첩 `<p>`는 무효 HTML이다.
    """
    parts = split_sentences(text)
    if not parts:
        return Markup("")
    return Markup("").join(Markup("<p>{}</p>").format(escape(p)) for p in parts)


# 제목 상한. 프롬프트가 40자를 요구하지만 지시 준수가 약한 모델에서도 화면이 버텨야 한다.
_TITLE_CHARS = 60

# 점수의 출처 배지. CSS 클래스는 영어를 그대로 쓰고 **보이는 글자만** 한글이다 —
# `rubric.COMPUTED`·`UNAVAILABLE`이 DB에 들어가는 값이라 그쪽을 건드리면 안 된다.
_SOURCE_LABELS = {"computed": "계산", "judged": "판정", "unavailable": "근거 없음"}


def _headline(title: str | None, description: str, slug: str) -> str:
    """제목 — interview가 쓴 것을 쓰고, 없거나 너무 길면 원문·slug로 물러난다.

    코드가 문장을 다듬지 않는다(불변식 7). 여기서 하는 건 **고르기**뿐이다 —
    LLM이 제목 대신 문단을 넣으면 h1이 세 줄이 되므로 그때는 원문이 차라리 낫다.
    """
    cleaned = (title or "").strip()
    if cleaned and len(cleaned) <= _TITLE_CHARS:
        return cleaned
    return description or slug


def _env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["sentences"] = _sentences
    env.filters["summary_line"] = _summary_line
    env.filters["source_label"] = lambda source: _SOURCE_LABELS.get(source, source)
    return env


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
        # 제목은 interview가 쓴다 (불변식 7). 길거나 비면 원문으로 물러난다 —
        # 예전 실행의 interview_json에는 이 키가 아예 없다.
        "title": _headline(interview.get("title"), run.get("description", ""), slug),
        "constraints": interview.get("constraints") or [],
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
