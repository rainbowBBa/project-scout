import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from scout.schemas import Candidate, Component, Fact, Interview, Verdict

DDL = """
CREATE TABLE IF NOT EXISTS runs (
    slug TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL,
    interview_json TEXT
);

CREATE TABLE IF NOT EXISTS components (
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    why TEXT NOT NULL,
    necessity TEXT NOT NULL,
    necessity_reason TEXT NOT NULL,
    priority INTEGER NOT NULL,
    approach_notes TEXT NOT NULL,
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
"""


def _db_path(slug: str, runs_dir: str | None) -> Path:
    if runs_dir is None:
        from scout.config import (
            Settings,  # 지연 임포트 — runs_dir이 주어지면 Settings()가 불필요하다
        )

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


# ── components ───────────────────────────────────────────────────────────


def upsert_components(
    slug: str, components: list[Component], *, runs_dir: str | None = None
) -> None:
    # analyze는 실행마다 요소 전체를 다시 도출한다 — 전체 교체가 재실행 시맨틱과 맞다.
    with _conn(slug, runs_dir) as conn:
        conn.execute("DELETE FROM components WHERE slug = ?", (slug,))
        conn.executemany(
            """
            INSERT INTO components (slug, name, kind, why, necessity, necessity_reason, priority, approach_notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    slug,
                    c.name,
                    c.kind,
                    c.why,
                    c.necessity,
                    c.necessity_reason,
                    c.priority,
                    c.approach_notes,
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
                why=r["why"],
                necessity=r["necessity"],
                necessity_reason=r["necessity_reason"],
                priority=r["priority"],
                approach_notes=r["approach_notes"],
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


def get_facts(slug: str, candidate: str, *, runs_dir: str | None = None) -> list[Fact]:
    with _conn(slug, runs_dir) as conn:
        rows = conn.execute(
            "SELECT * FROM facts WHERE slug = ? AND candidate = ?", (slug, candidate)
        ).fetchall()
        return [
            Fact(
                id=r["fact_id"],
                label=r["label"],
                value=r["value"],
                url=r["url"],
                retrieved_at=r["retrieved_at"],
            )
            for r in rows
        ]


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
                    dossier=[
                        Fact(
                            id=f["fact_id"],
                            label=f["label"],
                            value=f["value"],
                            url=f["url"],
                            retrieved_at=f["retrieved_at"],
                        )
                        for f in facts
                    ],
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


def clear_picks(slug: str, component: str, *, runs_dir: str | None = None) -> None:
    with _conn(slug, runs_dir) as conn:
        conn.execute(
            "DELETE FROM picks WHERE slug = ? AND component = ?", (slug, component)
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
