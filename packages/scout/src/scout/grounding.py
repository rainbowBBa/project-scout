"""judge의 인용을 dossier와 대조한다. **LLM을 쓰지 않는다.**

`citations LEFT JOIN facts`(store.get_ungrounded_citations)가 본체다 — 03-저장.md
"grounding 검증이 SQL 한 줄". 이 대조가 없으면 judge가 없는 사실을 지어내도 알 수
없고, 그러면 이 도구는 그냥 LLM에게 물어보는 것과 같아진다 (불변식 4).

강등 규칙은 3-verify.md "실패 처리"를 따른다 — 2차 위반은 confidence를 한 단계 내리고,
인용이 하나도 없는 판정도 마찬가지다. 근거 0개 판정은 판정이 아니다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scout import store

if TYPE_CHECKING:
    from scout.schemas import Verdict

_LOWER = {"high": "medium", "medium": "low", "low": "low"}

NO_CITATION_CLAIM = "인용한 사실이 없음 — 판정 전체가 dossier 근거 없이 내려졌다"


def ungrounded(slug: str, candidate: str, *, runs_dir: str | None = None) -> list[str]:
    """`candidate`가 인용한 것 중 dossier(facts)에 없는 fact_id.

    저장된 citations를 대조하므로 `store.upsert_verdict` **뒤에** 부른다.
    """
    return [
        fact_id
        for cited_candidate, fact_id in store.get_ungrounded_citations(
            slug, runs_dir=runs_dir
        )
        if cited_candidate == candidate
    ]


def strip_ungrounded(verdict: Verdict, violations: list[str]) -> Verdict:
    """위반 인용을 citations에서 빼고 unsupported_claims로 옮긴 사본.

    지우기만 하면 judge가 무엇을 지어냈는지가 사라진다. DB에는 dossier 안의 인용만
    남기되(불변식 4), 지어낸 id는 unsupported_claims에 기록으로 남긴다.
    """
    if not violations:
        return verdict
    bogus = set(violations)
    return verdict.model_copy(
        update={
            "citations": [c for c in verdict.citations if c not in bogus],
            "unsupported_claims": [
                *verdict.unsupported_claims,
                *(f"dossier에 없는 사실을 인용함: {fact_id}" for fact_id in violations),
            ],
        }
    )


def lower_confidence(verdict: Verdict) -> Verdict:
    """한 단계 낮춘다. low가 바닥이다."""
    return verdict.model_copy(update={"confidence": _LOWER[verdict.confidence]})


def force_low(verdict: Verdict) -> Verdict:
    """재판정에도 위반이 남은 판정을 바로 low로 내린다.

    한 단계씩이 아니라 바닥까지 내리는 이유는 3-verify.md "실패 처리" — 지어낸 인용이
    두 번 나온 판정은 confidence 자체를 믿을 수 없다.
    """
    return verdict.model_copy(update={"confidence": "low"})


def degrade_if_uncited(verdict: Verdict) -> Verdict:
    """인용이 빈 판정을 강등한다. 이미 low면 confidence는 그대로고 이유만 남는다."""
    if verdict.citations:
        return verdict
    return lower_confidence(verdict).model_copy(
        update={"unsupported_claims": [*verdict.unsupported_claims, NO_CITATION_CLAIM]}
    )
