"""maturity·risk 점수 공식 (stages/4-evaluate.md "점수 공식").

이 두 점수를 코드가 계산하는 이유는 불변식 5다 — judge가 낡은 사실을 무시해도 계산이
잡는 이중 안전망이다. "마지막 릴리스 1,690일 전"의 성숙도는 계산이지 판단이 아니다.

가중치 매핑도 정규화도 없다. 두 공식과 그 근거 문자열뿐이다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from scout.schemas import Fact

COMPUTED = "computed"
UNAVAILABLE = "unavailable"

# 경과일 → 점수. 릴리스 최근성과 커밋 활성이 같은 구간을 쓴다.
_AGE_BANDS = ((90, 5), (365, 4), (730, 3), (1095, 2))
# 기여자 수 → 점수. 세 신호 중 버스 팩터를 보는 것은 이것뿐이다.
_CONTRIB_BANDS = ((10, 5), (5, 4), (3, 3), (2, 2))

_PERMISSIVE = ("mit", "apache", "bsd", "isc", "unlicense", "zlib", "python-2.0", "0bsd")
# MPL은 파일 단위 copyleft다 — 허용형으로 세지 않는다. lgpl은 gpl에 걸린다.
_COPYLEFT = ("gpl", "agpl", "eupl", "sspl", "osl", "cc-by-sa", "mpl", "cddl", "epl")

_REGISTRY_PREFIXES = ("npm.", "pypi.")
_LICENSE_IDS = ("npm.license", "pypi.license")
_RELEASE_IDS = ("npm.last_release", "pypi.last_release")
_DEPRECATED_IDS = ("npm.deprecated", "pypi.yanked")


def _by_id(facts: Sequence[Fact]) -> dict[str, str]:
    return {f.id: f.value for f in facts}


def _flag(raw: str | None) -> bool:
    """저장된 bool 문자열과 npm의 deprecated 메시지를 함께 다룬다.

    facts.value는 전부 str(value)로 들어오므로 False도 "False"라는 문자열로 남는다.
    npm.deprecated는 bool이 아니라 사용 중단 안내 문장으로 오기도 한다.
    """
    if raw is None:
        return False
    return raw.strip().lower() not in ("", "false", "none", "0")


def _int(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(float(raw.strip()))
    except ValueError:
        return None


def _days_since(raw: str | None, now: datetime) -> int | None:
    if not raw:
        return None
    try:
        moment = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0, (now - moment).days)


def _age_score(days: int) -> int:
    for limit, score in _AGE_BANDS:
        if days <= limit:
            return score
    return 1


def _contributor_score(count: int) -> int:
    for limit, score in _CONTRIB_BANDS:
        if count >= limit:
            return score
    return 1


def _license_kind(name: str) -> str:
    lowered = name.lower()
    if not lowered:
        return "unknown"
    if any(token in lowered for token in _COPYLEFT):
        return "copyleft"
    if any(token in lowered for token in _PERMISSIVE):
        return "permissive"
    return "unknown"


def maturity(
    facts: Sequence[Fact], *, now: datetime | None = None
) -> tuple[int | None, str]:
    """세 신호(릴리스 최근성·커밋 활성·기여자 수)의 최소값. 없는 신호는 채우지 않는다.

    최소값을 쓰는 이유는 가장 약한 신호가 성숙도를 결정하기 때문이다 — 별이 5만 개라도
    3년째 커밋이 없으면 성숙한 게 아니다. 없는 신호를 5로 채우면 조회 실패가 좋은
    점수로 둔갑하고, 1로 채우면 gh 사실이 없는 후보가 전부 최하점이 된다.
    """
    now = now or datetime.now(UTC)
    values = _by_id(facts)

    if _flag(values.get("gh.archived")):
        return 1, "gh.archived → 1 (보관된 저장소는 다른 신호를 보지 않는다)"

    signals: list[int] = []
    parts: list[str] = []

    release = min(
        (
            (days, fact_id)
            for fact_id in _RELEASE_IDS
            if (days := _days_since(values.get(fact_id), now)) is not None
        ),
        default=None,
    )
    if release is not None:
        days, fact_id = release
        score = _age_score(days)
        signals.append(score)
        parts.append(f"{fact_id} {days}일 전 → {score}")

    commit_days = _days_since(values.get("gh.last_commit"), now)
    if commit_days is not None:
        score = _age_score(commit_days)
        signals.append(score)
        parts.append(f"gh.last_commit {commit_days}일 전 → {score}")

    contributors = _int(values.get("gh.contributors"))
    if contributors is not None:
        score = _contributor_score(contributors)
        signals.append(score)
        parts.append(f"gh.contributors {contributors}명 → {score}")

    if not signals:
        return (
            None,
            "성숙도를 계산할 사실이 없다 — 릴리스·커밋·기여자 신호가 하나도 없다",
        )

    lowest = min(signals)
    return lowest, f"{', '.join(parts)} → 최소 {lowest}"


def risk(facts: Sequence[Fact]) -> tuple[int | None, str]:
    """높을수록 안전한 1~5. 취약점 → 라이선스 순으로 감점하고 1~5로 클램프한다.

    osv.*가 없으면 취약점 항목을 건너뛴다 — "조회하지 않았다"를 "0건이다"로 대접하면
    risk가 근거 없이 후해진다. 취약점은 버전을 특정해서만 묻기 때문에(search._topup_vulns)
    레지스트리에서 버전을 못 찾은 후보는 지금도 이 경로로 온다.
    """
    values = _by_id(facts)

    for fact_id in _DEPRECATED_IDS:
        if _flag(values.get(fact_id)):
            return 1, f"{fact_id} → 1 (사용 중단·철회된 패키지)"

    parts: list[str] = []
    score: int | None = None

    vulns = _int(values.get("osv.vulns"))
    if vulns is not None:
        score = 5 if vulns == 0 else 3 if vulns <= 2 else 2
        parts.append(f"osv.vulns {vulns}건 → {score}")
        if (values.get("osv.max_severity") or "").strip().upper() == "CRITICAL":
            score = 1
            parts.append("osv.max_severity CRITICAL → 1")

    license_id = next((f for f in _LICENSE_IDS if values.get(f)), None)
    # 레지스트리 사실이 있는데 라이선스만 없으면 그건 진짜 "불명"이다. 레지스트리 자체가
    # 없는 후보(software·method)는 판단 근거가 없는 것이므로 이 항목을 건너뛴다.
    if license_id or any(k.startswith(_REGISTRY_PREFIXES) for k in values):
        if score is None:
            score = 5
            parts.append("osv 미조회 — 취약점 항목 제외")
        name = (values.get(license_id) or "").strip() if license_id else ""
        kind = _license_kind(name)
        if kind == "permissive":
            parts.append(f"{license_id} {name} → 유지")
        else:
            score -= 1
            label = f"{license_id} {name}" if name else "라이선스 불명"
            parts.append(f"{label}({kind}) → -1")

    if score is None:
        return (
            None,
            "위험을 계산할 사실이 없다 — 취약점·라이선스·사용중단 신호가 하나도 없다",
        )

    clamped = max(1, min(5, score))
    return clamped, f"{', '.join(parts)} → {clamped}"
