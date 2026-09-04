"""취약점 조회 배선을 검사한다 — 네트워크를 쓰지 않는다 (툴 대역).

검증하는 주장: **취약점은 버전을 특정해서만 묻는다.**

버전 없이 OSV에 물으면 그 패키지에 **한 번이라도** 영향을 준 취약점이 전부 온다.
실측에서 `django@3.2.0`이 63건이었고, 버전을 빼면 성숙한 패키지가 예외 없이
"취약점 수십 건"이 되어 `rubric.risk`가 그만큼 깎인다 — **성숙도가 위험으로 뒤집힌다.**
그래서 `_topup_vulns`는 레지스트리에서 읽은 `latest_version`을 넘기고, 버전을 못 찾으면
**조회하지 않고** `gaps`에 남긴다. 안 묻는 쪽이 틀린 숫자보다 낫다는 판단이고,
그때 risk는 "osv 미조회 — 취약점 항목 제외" 경로로 간다.

0건도 사실이다 — `osv.vulns`가 "0"으로 남아야 `rubric.risk`가 5점을 준다.
빈 값과 0을 같이 취급하면 취약점 없는 패키지가 "미조회"로 떨어진다.
"""

import asyncio

from scout import rubric
from scout.agentkit import ToolCall
from scout_net_mcp.providers import osv as osv_provider
from scout.schemas import Fact
from scout.stages.search import (
    _registry_facts,
    _topup_vulns,
    call_matches,
    topup_dossier,
)

NOW = "2026-09-04T00:00:00Z"


class _SpyOsv:
    """`osv_query` 툴 대역. 호출 인자를 기록한다 — 무엇을 물었는지가 검사 대상이다."""

    name = "osv_query"

    def __init__(self, payload: dict | None = None) -> None:
        self.calls: list[dict] = []
        self.payload = payload if payload is not None else _payload(0)

    async def ainvoke(self, args: dict) -> dict:
        self.calls.append(args)
        return self.payload


def _payload(vulns: int, max_severity: str | None = None, ids: str = "") -> dict:
    return {
        "name": "lodash",
        "ecosystem": "npm",
        "version": "4.17.11",
        "vulns": vulns,
        "max_severity": max_severity,
        "ids": ids,
        "url": "https://osv.dev/list?q=lodash&ecosystem=npm",
    }


def _fact(fact_id: str, value: str) -> Fact:
    return Fact(id=fact_id, label=fact_id, value=value, url=None, retrieved_at=NOW)


def _topup(facts: list[Fact], spy: _SpyOsv, name: str = "lodash"):
    return asyncio.run(_topup_vulns(name, facts, {"osv_query": spy}, NOW))


# ── 무엇을 묻는가 ────────────────────────────────────────────────────────


def test_registry_version_is_what_gets_asked():
    """★ 방금 읽은 latest_version을 그대로 넘긴다 — 그게 "지금 설치될 버전"이다."""
    spy = _SpyOsv()

    _topup([_fact("npm.latest_version", "4.17.21")], spy)

    assert spy.calls == [
        {"name": "lodash", "ecosystem": "npm", "version": "4.17.21"}
    ]


def test_pypi_ecosystem_keeps_its_casing():
    """OSV는 ecosystem 표기의 대소문자를 가린다 — "pypi"로 보내면 0건이 온다."""
    spy = _SpyOsv()

    _topup([_fact("pypi.latest_version", "5.0.1")], spy, name="django")

    assert spy.calls[0]["ecosystem"] == "PyPI"


def test_npm_wins_when_both_registries_have_a_version():
    """한 후보가 두 레지스트리에 다 있으면 한 번만 묻는다 — 사실이 갈리면 안 된다."""
    spy = _SpyOsv()

    _topup(
        [_fact("npm.latest_version", "1.0.0"), _fact("pypi.latest_version", "2.0.0")],
        spy,
    )

    assert len(spy.calls) == 1
    assert spy.calls[0]["version"] == "1.0.0"


def test_no_version_means_no_query(monkeypatch):
    """★ 버전이 없으면 묻지 않는다 — 틀린 숫자보다 없는 게 낫다.

    실측: 버전 없는 조회는 `django`에서 63건을 돌려줬다. 그 숫자가 risk를 깎으면
    "오래 유지된 패키지일수록 위험하다"가 되어 판단이 거꾸로 선다.
    """
    spy = _SpyOsv()

    facts, gaps = _topup([_fact("gh.stars", "50000")], spy)

    assert spy.calls == [], "버전 없이 취약점을 물었다"
    assert facts == []
    assert any("버전을 특정하지 못해" in g for g in gaps), gaps


def test_lookup_failure_becomes_a_gap():
    """조회 실패가 파이프라인을 죽이지 않는다 (불변식 11)."""

    class _Broken(_SpyOsv):
        async def ainvoke(self, args: dict) -> dict:
            raise RuntimeError("503 Service Unavailable")

    facts, gaps = _topup([_fact("npm.latest_version", "4.17.21")], _Broken())

    assert facts == []
    assert any("osv_query 조회 실패" in g for g in gaps), gaps


# ── 무엇이 사실로 남는가 ────────────────────────────────────────────────


def test_zero_vulns_is_a_fact():
    """★ 0건도 사실이다 — 없으면 `rubric.risk`가 5점을 줄 근거가 없어진다."""
    facts, gaps = _topup([_fact("npm.latest_version", "4.17.21")], _SpyOsv(_payload(0)))

    by_id = {f.id: f.value for f in facts}
    assert by_id["osv.vulns"] == "0"
    # 0건이면 등급도 ID도 없다 — 빈 값을 사실로 만들지 않는다
    assert "osv.max_severity" not in by_id
    assert "osv.ids" not in by_id
    assert gaps == []


def test_vulns_carry_severity_and_ids():
    payload = _payload(7, "CRITICAL", "GHSA-29mw-wpgm-hmr9, GHSA-35jh-r3h4-6jhm")
    facts, _ = _topup([_fact("npm.latest_version", "4.17.11")], _SpyOsv(payload))

    by_id = {f.id: f.value for f in facts}
    assert by_id["osv.vulns"] == "7"
    assert by_id["osv.max_severity"] == "CRITICAL"
    assert "GHSA-29mw-wpgm-hmr9" in by_id["osv.ids"]
    assert all(f.url and "osv.dev" in f.url for f in facts), "출처 링크가 없다"


def test_fact_ids_follow_the_source_item_rule():
    """`<출처>.<항목>` 규칙 — grounding이 SQL로 대조하는 키다."""
    call = ToolCall("osv_query", {"name": "lodash"}, _payload(1, "HIGH", "GHSA-x"), "")

    ids = [f.id for f in _registry_facts(call, NOW)]

    assert ids == ["osv.vulns", "osv.max_severity", "osv.ids"]


def test_osv_facts_do_not_attach_to_another_candidate():
    """다른 후보의 취약점이 이 후보에 붙으면 판정의 근거가 뒤섞인다."""
    call = ToolCall("osv_query", {"name": "lodash"}, _payload(7, "CRITICAL"), "")

    assert call_matches(call, "lodash")
    assert not call_matches(call, "underscore")


# ── kind 라우팅 ─────────────────────────────────────────────────────────


def _run_topup(kind: str, facts: list[Fact], spy: _SpyOsv):
    return asyncio.run(topup_dossier("lodash", kind, facts, {"osv_query": spy}, NOW))


def test_library_gets_vulns_checked():
    spy = _SpyOsv()

    _run_topup("library", [_fact("npm.latest_version", "4.17.21")], spy)

    assert len(spy.calls) == 1


def test_method_is_not_asked_about_vulns():
    """method 후보는 패키지가 아니다 — 물을 대상이 없다."""
    spy = _SpyOsv()

    _, gaps = _run_topup("method", [], spy)

    assert spy.calls == []
    assert any("레지스트리 없음" in g for g in gaps)


def test_existing_osv_facts_are_not_re_queried():
    """에이전트가 이미 물었으면 다시 묻지 않는다 — top-up은 빈 자리만 채운다."""
    spy = _SpyOsv()

    _run_topup(
        "library",
        [_fact("npm.latest_version", "4.17.21"), _fact("osv.vulns", "0")],
        spy,
    )

    assert spy.calls == []


# ── 점수까지 이어지는가 ─────────────────────────────────────────────────


def test_risk_uses_the_vuln_facts():
    """★ 절단선을 되돌린 값어치 — risk가 "미조회"가 아니라 근거를 갖는다."""
    dossier = [
        _fact("npm.license", "MIT"),
        _fact("npm.latest_version", "4.17.11"),
        _fact("osv.vulns", "7"),
        _fact("osv.max_severity", "CRITICAL"),
    ]

    score, reason = rubric.risk(dossier)

    assert score == 1
    assert "osv.vulns 7건" in reason and "CRITICAL" in reason
    assert "미조회" not in reason, "취약점을 조회했는데 미조회 경로로 갔다"


def test_clean_package_scores_full_risk():
    dossier = [_fact("npm.license", "MIT"), _fact("osv.vulns", "0")]

    score, reason = rubric.risk(dossier)

    assert score == 5
    assert "osv.vulns 0건" in reason


def test_unqueried_package_still_takes_the_excluded_path():
    """조회하지 않은 후보는 예전 경로 그대로 — 0건으로 대접하지 않는다."""
    score, reason = rubric.risk([_fact("npm.license", "MIT")])

    assert score == 5
    assert "미조회" in reason


# ── provider 쪽 등급 추출 ───────────────────────────────────────────────


def test_highest_severity_wins():
    """여러 취약점 중 가장 높은 등급이 max_severity다 — 평균이 아니다."""
    vulns = [
        {"database_specific": {"severity": "LOW"}},
        {"database_specific": {"severity": "CRITICAL"}},
        {"database_specific": {"severity": "MODERATE"}},
    ]

    assert osv_provider._max_severity(vulns) == "CRITICAL"


def test_cvss_vector_is_not_guessed_into_a_grade():
    """★ CVSS 벡터는 파싱하지 않는다 — 모르는 것을 추측해 채우면 risk가 흔들린다.

    등급이 없으면 `max_severity`가 None이고 사실이 되지 않는다. 그때 risk는 건수만
    보고 판단하며, 그게 정직한 상태다.
    """
    vulns = [{"severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L"}]}]

    assert osv_provider._max_severity(vulns) is None
