import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from scout.schemas import (
    Architecture,
    Candidate,
    Component,
    Fact,
    FinalDesign,
    Interview,
    Verdict,
)

DDL = """
CREATE TABLE IF NOT EXISTS runs (
    slug TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL,
    interview_json TEXT
);

CREATE TABLE IF NOT EXISTS designs (
    slug TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    shape TEXT NOT NULL,
    data_flow TEXT NOT NULL,
    build_order_json TEXT NOT NULL,
    open_questions_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS components (
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    role_in_design TEXT NOT NULL,
    decision_question TEXT NOT NULL,
    alternatives_json TEXT NOT NULL,
    constraints_json TEXT NOT NULL,
    needs_comparison INTEGER NOT NULL,
    no_comparison_reason TEXT NOT NULL,
    necessity TEXT NOT NULL,
    necessity_reason TEXT NOT NULL,
    priority INTEGER NOT NULL,
    approach_notes TEXT NOT NULL,
    search_hints_json TEXT NOT NULL,
    PRIMARY KEY (slug, name)
);

CREATE TABLE IF NOT EXISTS candidates (
    slug TEXT NOT NULL,
    component TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    what_it_is TEXT NOT NULL,
    PRIMARY KEY (slug, component, name)
);

CREATE TABLE IF NOT EXISTS facts (
    slug TEXT NOT NULL,
    candidate TEXT NOT NULL,
    fact_id TEXT NOT NULL,
    label TEXT NOT NULL,
    value TEXT NOT NULL,
    url TEXT,
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (slug, candidate, fact_id)
);

CREATE TABLE IF NOT EXISTS gaps (
    slug TEXT NOT NULL,
    candidate TEXT NOT NULL,
    note TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verdicts (
    slug TEXT NOT NULL,
    candidate TEXT NOT NULL,
    solves_it INTEGER NOT NULL,
    solves_reason TEXT NOT NULL,
    confidence TEXT NOT NULL,
    pros_json TEXT NOT NULL,
    cons_json TEXT NOT NULL,
    caveats_json TEXT NOT NULL,
    unsupported_claims_json TEXT NOT NULL,
    grounding_violations INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (slug, candidate)
);

CREATE TABLE IF NOT EXISTS citations (
    slug TEXT NOT NULL,
    candidate TEXT NOT NULL,
    fact_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scores (
    slug TEXT NOT NULL,
    candidate TEXT NOT NULL,
    criterion TEXT NOT NULL,
    score INTEGER,
    source TEXT NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY (slug, candidate, criterion)
);

CREATE TABLE IF NOT EXISTS picks (
    slug TEXT NOT NULL,
    component TEXT NOT NULL,
    candidate TEXT NOT NULL,
    rank INTEGER,
    rejected_reason TEXT,
    winner_reason TEXT,
    runner_up_note TEXT,
    margin TEXT
);

CREATE TABLE IF NOT EXISTS final_designs (
    slug TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    shape TEXT NOT NULL,
    data_flow TEXT NOT NULL,
    changes_from_design_json TEXT NOT NULL,
    stack_rationale TEXT NOT NULL,
    integration_notes_json TEXT NOT NULL,
    combination_risks_json TEXT NOT NULL,
    build_order_json TEXT NOT NULL,
    unresolved_json TEXT NOT NULL
);
"""


def _db_path(slug: str, runs_dir: str | None) -> Path:
    if runs_dir is None:
        # 지연 임포트 — runs_dir이 주어지면 Settings()가 불필요하다
        from scout.config import Settings

        runs_dir = Settings().scout_runs_dir
    return Path(runs_dir) / slug / "scout.db"


@contextmanager
def _conn(slug: str, runs_dir: str | None = None) -> Iterator[sqlite3.Connection]:
    path = _db_path(slug, runs_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ── runs ─────────────────────────────────────────────────────────────────


def upsert_run(
    slug: str,
    description: str,
    created_at: str,
    interview: Interview,
    *,
    runs_dir: str | None = None,
) -> None:
    with _conn(slug, runs_dir) as conn:
        conn.execute(
            """
            INSERT INTO runs (slug, description, created_at, interview_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                description = excluded.description,
                interview_json = excluded.interview_json
            """,
            (slug, description, created_at, interview.model_dump_json()),
        )


def get_run(slug: str, *, runs_dir: str | None = None) -> dict | None:
    with _conn(slug, runs_dir) as conn:
        row = conn.execute("SELECT * FROM runs WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            return None
        interview = (
            Interview.model_validate_json(row["interview_json"])
            if row["interview_json"]
            else None
        )
        return {
            "slug": row["slug"],
            "description": row["description"],
            "created_at": row["created_at"],
            "interview": interview.model_dump() if interview else None,
        }


# ── designs / components ─────────────────────────────────────────────────


def upsert_design(
    slug: str, architecture: Architecture, *, runs_dir: str | None = None
) -> None:
    """조사 전 기본틀(v1). evaluate가 확정한 v2는 final_designs로 따로 들어간다 —
    이 행은 덮어쓰지 않는다. 두 버전의 대조가 보고서의 재료다 (03-저장.md).
    """
    with _conn(slug, runs_dir) as conn:
        conn.execute(
            """
            INSERT INTO designs (slug, summary, shape, data_flow, build_order_json, open_questions_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                summary = excluded.summary,
                shape = excluded.shape,
                data_flow = excluded.data_flow,
                build_order_json = excluded.build_order_json,
                open_questions_json = excluded.open_questions_json
            """,
            (
                slug,
                architecture.summary,
                architecture.shape,
                architecture.data_flow,
                json.dumps(architecture.build_order, ensure_ascii=False),
                json.dumps(architecture.open_questions, ensure_ascii=False),
            ),
        )


def get_design(slug: str, *, runs_dir: str | None = None) -> Architecture | None:
    with _conn(slug, runs_dir) as conn:
        row = conn.execute("SELECT * FROM designs WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        return None
    return Architecture(
        summary=row["summary"],
        shape=row["shape"],
        data_flow=row["data_flow"],
        build_order=json.loads(row["build_order_json"]),
        open_questions=json.loads(row["open_questions_json"]),
    )


def upsert_components(
    slug: str, components: list[Component], *, runs_dir: str | None = None
) -> None:
    # design은 실행마다 결정 지점 전체를 다시 도출한다 — 전체 교체가 재실행 시맨틱과 맞다.
    with _conn(slug, runs_dir) as conn:
        conn.execute("DELETE FROM components WHERE slug = ?", (slug,))
        conn.executemany(
            """
            INSERT INTO components (
                slug, name, kind, role_in_design, decision_question,
                alternatives_json, constraints_json,
                needs_comparison, no_comparison_reason,
                necessity, necessity_reason, priority, approach_notes, search_hints_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    slug,
                    c.name,
                    c.kind,
                    c.role_in_design,
                    c.decision_question,
                    json.dumps(c.alternatives, ensure_ascii=False),
                    json.dumps(c.constraints, ensure_ascii=False),
                    int(c.needs_comparison),
                    c.no_comparison_reason,
                    c.necessity,
                    c.necessity_reason,
                    c.priority,
                    c.approach_notes,
                    # search_hints를 저장한다 — 상태로만 넘기면 재실행 경로에서 사라져
                    # design이 만든 효과가 소멸한다 (03-저장.md)
                    json.dumps(c.search_hints, ensure_ascii=False),
                )
                for c in components
            ],
        )


def get_components(slug: str, *, runs_dir: str | None = None) -> list[Component]:
    with _conn(slug, runs_dir) as conn:
        rows = conn.execute(
            "SELECT * FROM components WHERE slug = ? ORDER BY priority ASC", (slug,)
        ).fetchall()
        return [
            Component(
                name=r["name"],
                kind=r["kind"],
                role_in_design=r["role_in_design"],
                decision_question=r["decision_question"],
                alternatives=json.loads(r["alternatives_json"]),
                constraints=json.loads(r["constraints_json"]),
                needs_comparison=bool(r["needs_comparison"]),
                no_comparison_reason=r["no_comparison_reason"],
                necessity=r["necessity"],
                necessity_reason=r["necessity_reason"],
                priority=r["priority"],
                approach_notes=r["approach_notes"],
                search_hints=json.loads(r["search_hints_json"]),
            )
            for r in rows
        ]


# ── candidates / facts / gaps ───────────────────────────────────────────


def upsert_candidate(
    slug: str, candidate: Candidate, *, runs_dir: str | None = None
) -> None:
    with _conn(slug, runs_dir) as conn:
        conn.execute(
            """
            INSERT INTO candidates (slug, component, name, kind, what_it_is)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(slug, component, name) DO UPDATE SET
                kind = excluded.kind,
                what_it_is = excluded.what_it_is
            """,
            (
                slug,
                candidate.component,
                candidate.name,
                candidate.kind,
                candidate.what_it_is,
            ),
        )
        _upsert_facts(conn, slug, candidate.name, candidate.dossier)
        for note in candidate.dossier_gaps:
            conn.execute(
                "INSERT INTO gaps (slug, candidate, note) VALUES (?, ?, ?)",
                (slug, candidate.name, note),
            )


def upsert_facts(
    slug: str, candidate: str, facts: list[Fact], *, runs_dir: str | None = None
) -> None:
    with _conn(slug, runs_dir) as conn:
        _upsert_facts(conn, slug, candidate, facts)


def _upsert_facts(
    conn: sqlite3.Connection, slug: str, candidate: str, facts: list[Fact]
) -> None:
    conn.executemany(
        """
        INSERT INTO facts (slug, candidate, fact_id, label, value, url, retrieved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(slug, candidate, fact_id) DO UPDATE SET
            label = excluded.label,
            value = excluded.value,
            url = excluded.url,
            retrieved_at = excluded.retrieved_at
        """,
        [
            (slug, candidate, f.id, f.label, f.value, f.url, f.retrieved_at)
            for f in facts
        ],
    )


def add_gap(
    slug: str, candidate: str, note: str, *, runs_dir: str | None = None
) -> None:
    with _conn(slug, runs_dir) as conn:
        conn.execute(
            "INSERT INTO gaps (slug, candidate, note) VALUES (?, ?, ?)",
            (slug, candidate, note),
        )


def get_all_gaps(slug: str, *, runs_dir: str | None = None) -> list[dict]:
    """report용 — 후보뿐 아니라 요소·단계 이름으로 남은 gap까지 전부 덤프한다."""
    with _conn(slug, runs_dir) as conn:
        rows = conn.execute(
            "SELECT candidate, note FROM gaps WHERE slug = ?", (slug,)
        ).fetchall()
        return [dict(r) for r in rows]


def _fact_from_row(row: sqlite3.Row) -> Fact:
    return Fact(
        id=row["fact_id"],
        label=row["label"],
        value=row["value"],
        url=row["url"],
        retrieved_at=row["retrieved_at"],
    )


def get_facts(slug: str, candidate: str, *, runs_dir: str | None = None) -> list[Fact]:
    with _conn(slug, runs_dir) as conn:
        rows = conn.execute(
            "SELECT * FROM facts WHERE slug = ? AND candidate = ?", (slug, candidate)
        ).fetchall()
        return [_fact_from_row(r) for r in rows]


def get_gaps(slug: str, candidate: str, *, runs_dir: str | None = None) -> list[str]:
    with _conn(slug, runs_dir) as conn:
        rows = conn.execute(
            "SELECT note FROM gaps WHERE slug = ? AND candidate = ?", (slug, candidate)
        ).fetchall()
        return [r["note"] for r in rows]


def get_candidates(
    slug: str, component: str | None = None, *, runs_dir: str | None = None
) -> list[Candidate]:
    with _conn(slug, runs_dir) as conn:
        if component is None:
            rows = conn.execute(
                "SELECT * FROM candidates WHERE slug = ?", (slug,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM candidates WHERE slug = ? AND component = ?",
                (slug, component),
            ).fetchall()

        candidates = []
        for r in rows:
            facts = conn.execute(
                "SELECT * FROM facts WHERE slug = ? AND candidate = ?",
                (slug, r["name"]),
            ).fetchall()
            gaps = conn.execute(
                "SELECT note FROM gaps WHERE slug = ? AND candidate = ?",
                (slug, r["name"]),
            ).fetchall()
            candidates.append(
                Candidate(
                    component=r["component"],
                    name=r["name"],
                    kind=r["kind"],
                    what_it_is=r["what_it_is"],
                    dossier=[_fact_from_row(f) for f in facts],
                    dossier_gaps=[g["note"] for g in gaps],
                )
            )
        return candidates


# ── verdicts / citations ─────────────────────────────────────────────────


def upsert_verdict(
    slug: str,
    verdict: Verdict,
    *,
    grounding_violations: int = 0,
    runs_dir: str | None = None,
) -> None:
    with _conn(slug, runs_dir) as conn:
        conn.execute(
            """
            INSERT INTO verdicts (
                slug, candidate, solves_it, solves_reason, confidence,
                pros_json, cons_json, caveats_json, unsupported_claims_json, grounding_violations
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug, candidate) DO UPDATE SET
                solves_it = excluded.solves_it,
                solves_reason = excluded.solves_reason,
                confidence = excluded.confidence,
                pros_json = excluded.pros_json,
                cons_json = excluded.cons_json,
                caveats_json = excluded.caveats_json,
                unsupported_claims_json = excluded.unsupported_claims_json,
                grounding_violations = excluded.grounding_violations
            """,
            (
                slug,
                verdict.candidate,
                int(verdict.solves_it),
                verdict.solves_reason,
                verdict.confidence,
                json.dumps(verdict.pros, ensure_ascii=False),
                json.dumps(verdict.cons, ensure_ascii=False),
                json.dumps(verdict.caveats, ensure_ascii=False),
                json.dumps(verdict.unsupported_claims, ensure_ascii=False),
                grounding_violations,
            ),
        )
        # 재판정 시 이전 인용을 지우고 새로 쓴다 — citations에는 PK가 없어 그냥 두면 누적된다.
        conn.execute(
            "DELETE FROM citations WHERE slug = ? AND candidate = ?",
            (slug, verdict.candidate),
        )
        conn.executemany(
            "INSERT INTO citations (slug, candidate, fact_id) VALUES (?, ?, ?)",
            [(slug, verdict.candidate, fact_id) for fact_id in verdict.citations],
        )


def get_citations(
    slug: str, candidate: str, *, runs_dir: str | None = None
) -> list[str]:
    with _conn(slug, runs_dir) as conn:
        rows = conn.execute(
            "SELECT fact_id FROM citations WHERE slug = ? AND candidate = ?",
            (slug, candidate),
        ).fetchall()
        return [r["fact_id"] for r in rows]


def get_verdicts(slug: str, *, runs_dir: str | None = None) -> list[Verdict]:
    with _conn(slug, runs_dir) as conn:
        rows = conn.execute(
            """
            SELECT v.*, c.component AS component
            FROM verdicts v
            LEFT JOIN candidates c ON c.slug = v.slug AND c.name = v.candidate
            WHERE v.slug = ?
            """,
            (slug,),
        ).fetchall()
        verdicts = []
        for r in rows:
            citations = conn.execute(
                "SELECT fact_id FROM citations WHERE slug = ? AND candidate = ?",
                (slug, r["candidate"]),
            ).fetchall()
            verdicts.append(
                Verdict(
                    candidate=r["candidate"],
                    component=r["component"] or "",
                    solves_it=bool(r["solves_it"]),
                    solves_reason=r["solves_reason"],
                    pros=json.loads(r["pros_json"]),
                    cons=json.loads(r["cons_json"]),
                    caveats=json.loads(r["caveats_json"]),
                    confidence=r["confidence"],
                    citations=[c["fact_id"] for c in citations],
                    unsupported_claims=json.loads(r["unsupported_claims_json"]),
                )
            )
        return verdicts


def get_grounding_violations(
    slug: str, *, runs_dir: str | None = None
) -> dict[str, int]:
    with _conn(slug, runs_dir) as conn:
        rows = conn.execute(
            "SELECT candidate, grounding_violations FROM verdicts WHERE slug = ?",
            (slug,),
        ).fetchall()
        return {r["candidate"]: r["grounding_violations"] for r in rows}


def get_ungrounded_citations(
    slug: str, *, runs_dir: str | None = None
) -> list[tuple[str, str]]:
    """dossier(facts)에 없는 fact_id를 인용한 (candidate, fact_id) 목록 — grounding.py의 재료."""
    with _conn(slug, runs_dir) as conn:
        rows = conn.execute(
            """
            SELECT c.candidate, c.fact_id
            FROM citations c
            LEFT JOIN facts f ON c.slug = f.slug
                             AND c.candidate = f.candidate
                             AND c.fact_id = f.fact_id
            WHERE c.slug = ? AND f.fact_id IS NULL
            """,
            (slug,),
        ).fetchall()
        return [(r["candidate"], r["fact_id"]) for r in rows]


# ── scores / picks ───────────────────────────────────────────────────────


def set_score(
    slug: str,
    candidate: str,
    criterion: str,
    score: int | None,
    source: str,
    reason: str,
    *,
    runs_dir: str | None = None,
) -> None:
    with _conn(slug, runs_dir) as conn:
        conn.execute(
            """
            INSERT INTO scores (slug, candidate, criterion, score, source, reason)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug, candidate, criterion) DO UPDATE SET
                score = excluded.score,
                source = excluded.source,
                reason = excluded.reason
            """,
            (slug, candidate, criterion, score, source, reason),
        )


def get_scores(
    slug: str, candidate: str | None = None, *, runs_dir: str | None = None
) -> list[dict]:
    with _conn(slug, runs_dir) as conn:
        if candidate is None:
            rows = conn.execute(
                "SELECT * FROM scores WHERE slug = ?", (slug,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM scores WHERE slug = ? AND candidate = ?",
                (slug, candidate),
            ).fetchall()
        return [dict(r) for r in rows]


def add_pick(
    slug: str,
    component: str,
    candidate: str,
    *,
    rank: int | None = None,
    rejected_reason: str | None = None,
    winner_reason: str | None = None,
    runner_up_note: str | None = None,
    margin: str | None = None,
    runs_dir: str | None = None,
) -> None:
    with _conn(slug, runs_dir) as conn:
        conn.execute(
            """
            INSERT INTO picks (slug, component, candidate, rank, rejected_reason, winner_reason, runner_up_note, margin)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slug,
                component,
                candidate,
                rank,
                rejected_reason,
                winner_reason,
                runner_up_note,
                margin,
            ),
        )


# ── 재실행 — 단계가 자기 산출물을 교체한다 ───────────────────────────────

# picks는 요소별로 `clear_picks`가 따로 비운다
_STAGE_TABLES = {
    "design": (),
    "search": ("facts", "candidates"),
    "verify": ("citations", "verdicts"),
    "evaluate": ("scores",),
}


def clear_stage_output(slug: str, stage: str, *, runs_dir: str | None = None) -> None:
    """단계가 쓰기 전에 자기 산출물을 비운다.

    PK upsert만으로는 부족하다 — 재실행에서 `design`이 결정 지점 이름을 다르게 만들면
    이전 후보·판정이 다른 키로 남아 고아가 되고, `evaluate`가 그것까지 채점한다.

    `gaps`는 `candidate` 컬럼이 후보명·요소명·단계명을 겸해 단계별로 정확히 가를 수
    없다. 각 단계는 자기 단계명의 gap만 비우고, `search`는 자기가 다시 만들 후보·요소의
    gap까지 비운다.
    """
    if stage not in _STAGE_TABLES:
        raise ValueError(f"알 수 없는 단계: {stage}")
    with _conn(slug, runs_dir) as conn:
        conn.execute("DELETE FROM gaps WHERE slug = ? AND candidate = ?", (slug, stage))
        if stage == "search":
            conn.execute(
                """
                DELETE FROM gaps WHERE slug = ? AND candidate IN (
                    SELECT name FROM candidates WHERE slug = ?
                    UNION SELECT name FROM components WHERE slug = ?
                )
                """,
                (slug, slug, slug),
            )
        for table in _STAGE_TABLES[stage]:
            conn.execute(f"DELETE FROM {table} WHERE slug = ?", (slug,))


def clear_picks(slug: str, component: str, *, runs_dir: str | None = None) -> None:
    with _conn(slug, runs_dir) as conn:
        conn.execute(
            "DELETE FROM picks WHERE slug = ? AND component = ?", (slug, component)
        )


def upsert_final_design(
    slug: str, final: FinalDesign, *, runs_dir: str | None = None
) -> None:
    """확정 설계(v2). `designs`(v1) 행은 **건드리지 않는다** — 두 버전의 대조가
    보고서의 재료다 (03-저장.md "designs와 final_designs가 따로인 이유").
    """
    with _conn(slug, runs_dir) as conn:
        conn.execute(
            """
            INSERT INTO final_designs (
                slug, summary, shape, data_flow, changes_from_design_json,
                stack_rationale, integration_notes_json, combination_risks_json,
                build_order_json, unresolved_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                summary = excluded.summary,
                shape = excluded.shape,
                data_flow = excluded.data_flow,
                changes_from_design_json = excluded.changes_from_design_json,
                stack_rationale = excluded.stack_rationale,
                integration_notes_json = excluded.integration_notes_json,
                combination_risks_json = excluded.combination_risks_json,
                build_order_json = excluded.build_order_json,
                unresolved_json = excluded.unresolved_json
            """,
            (
                slug,
                final.summary,
                final.shape,
                final.data_flow,
                json.dumps(final.changes_from_design, ensure_ascii=False),
                final.stack_rationale,
                json.dumps(final.integration_notes, ensure_ascii=False),
                json.dumps(final.combination_risks, ensure_ascii=False),
                json.dumps(final.build_order, ensure_ascii=False),
                json.dumps(final.unresolved, ensure_ascii=False),
            ),
        )


def get_final_design(slug: str, *, runs_dir: str | None = None) -> FinalDesign | None:
    with _conn(slug, runs_dir) as conn:
        row = conn.execute(
            "SELECT * FROM final_designs WHERE slug = ?", (slug,)
        ).fetchone()
    if row is None:
        return None
    return FinalDesign(
        summary=row["summary"],
        shape=row["shape"],
        data_flow=row["data_flow"],
        changes_from_design=json.loads(row["changes_from_design_json"]),
        stack_rationale=row["stack_rationale"],
        integration_notes=json.loads(row["integration_notes_json"]),
        combination_risks=json.loads(row["combination_risks_json"]),
        build_order=json.loads(row["build_order_json"]),
        unresolved=json.loads(row["unresolved_json"]),
    )


def get_picks(
    slug: str, component: str | None = None, *, runs_dir: str | None = None
) -> list[dict]:
    with _conn(slug, runs_dir) as conn:
        if component is None:
            rows = conn.execute(
                "SELECT * FROM picks WHERE slug = ?", (slug,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM picks WHERE slug = ? AND component = ?",
                (slug, component),
            ).fetchall()
        return [dict(r) for r in rows]
