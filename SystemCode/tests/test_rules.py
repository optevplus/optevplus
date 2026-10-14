"""Rule register, engine and screening (SYSTEM_DESIGN.md §4.4, #17-#19) on the sample."""

import re
from pathlib import Path
from typing import Any

import pytest

from optev.assumptions import MAX_SHARE_OF_LOTS
from optev.contracts import Decision, Outcome, RuleSource, SiteIndicators, SupplyState
from optev.reasoning import rules as R
from optev.reasoning.screen import screen, screen_sites, write_decisions
from optev.sample import load

S = load()
RULES, ON_FAIL = R.load_register()


@pytest.fixture(scope="module")
def screened() -> tuple[list[Decision], dict[str, int]]:
    return screen_sites(S.sites, S.car_parks, S.indicators, {}, RULES, ON_FAIL)


# 3.1 · register ---------------------------------------------------------------------------

def test_register_is_the_file_the_engine_loads():
    assert [r.rule_id for r in RULES] == ["R01", "R02", "R03", "R04", "R05"]
    assert set(R.CHECKS) == {r.rule_id for r in RULES}
    assert all(r.source_ref and r.required_facts for r in RULES)
    assert {r.source for r in RULES} == set(RuleSource)  # all four source classes


def test_register_agrees_with_the_sample_references():
    sample = {r.rule_id: r for r in S.rules}
    for rule in RULES:
        ref = sample[rule.rule_id]
        assert (rule.source, rule.source_ref, rule.required_facts) == \
            (ref.source, ref.source_ref, ref.required_facts)
    assert S.rule_on_fail == ON_FAIL
    cited = {x[k] for group in S.references.values() for x in group
             for k in ("dataset_id", "doc_id", "assumption_id") if k in x}
    assert {r.source_ref for r in RULES} <= cited


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "register.toml"
    path.write_text(body, encoding="utf-8")
    return path


ENTRY = """[[rules]]
rule_id = "{rid}"
condition = "c"
source = "gov_dataset"
source_ref = "{ref}"
required_facts = [{facts}]
explanation_template = "t"
on_fail = "{on_fail}"
"""


@pytest.mark.parametrize(("body", "message"), [
    (ENTRY.format(rid="R01", ref="x", facts='"total_lots"', on_fail="reject") * 2, "duplicate"),
    (ENTRY.format(rid="R01", ref="x", facts='"total_lots"', on_fail="defer"), "on_fail"),
    (ENTRY.format(rid="R99", ref="x", facts='"total_lots"', on_fail="reject"), "no check"),
    (ENTRY.format(rid="R01", ref="", facts='"total_lots"', on_fail="reject"), "source_ref"),
    (ENTRY.format(rid="R01", ref="x", facts='"vibes"', on_fail="reject"), "unknown fact"),
    ("", "no rules"),
])
def test_malformed_register_is_refused(tmp_path, body, message):
    with pytest.raises(ValueError, match=message):
        R.load_register(_write(tmp_path, body))


# 3.2 · engine -----------------------------------------------------------------------------

def test_engine_matches_every_sample_reference_decision(screened):
    decisions, _ = screened
    expected = {d.site_id: d for d in S.decisions}
    assert len(decisions) == len(expected) == 30
    for got in decisions:
        ref = expected[got.site_id]
        assert got.outcome == ref.outcome, got.site_id
        assert [(r.rule_id, r.passed) for r in got.results] == \
            [(r.rule_id, r.passed) for r in ref.results], got.site_id


def test_room_is_reported_as_in_the_sample(screened):
    decisions, _ = screened
    expected = {d.site_id: d.results[2].detail for d in S.decisions}
    for d in decisions:
        if d.results[2].passed is not None:
            room = re.search(r"Room for (\d+)", d.results[2].detail or "")
            assert room and f"room {room.group(1)}" == expected[d.site_id]


def _facts(**over: object) -> dict[str, object]:
    base: dict[str, object] = {"kind": "hdb_car_park", "planning_area": "TM", "total_lots": 400,
                               "existing_connectors": 2, "car_park_type": "MULTI-STOREY CAR PARK",
                               "supply_state": "supply_active", "utilisation": 0.6}
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


def _run(**over: object) -> Decision:
    return R.evaluate("hdb:X", _facts(**over), RULES, ON_FAIL)


def test_missing_fact_defers_and_never_rejects():
    d = _run(total_lots=None)
    assert d.outcome is Outcome.DEFER
    assert d.unevaluated_rules == ["R01", "R03"] and d.failing_rules == []
    assert "missing total_lots" in (d.results[0].detail or "")


def test_reject_outranks_defer_and_every_rule_is_still_recorded():
    d = _run(supply_state="supply_idle", planning_area=None, car_park_type="BASEMENT CAR PARK")
    assert d.outcome is Outcome.REJECT
    assert d.failing_rules == ["R02", "R04"] and d.unevaluated_rules == ["R05"]
    assert len(d.results) == len(RULES)  # never stops at the first failure


def test_defer_outranks_conditional():
    d = _run(car_park_type="BASEMENT CAR PARK", planning_area=None)
    assert d.outcome is Outcome.DEFER and d.failing_rules == ["R02"]


def test_conditional_when_only_a_conditional_rule_fails():
    d = _run(car_park_type="Basement car park")
    assert d.outcome is Outcome.CONDITIONAL and d.failing_rules == ["R02"]
    assert "fire-safety review" in (d.results[1].detail or "")


def test_car_park_rule_does_not_apply_elsewhere():
    d = _run(kind="hawker_centre", car_park_type=None, total_lots=None)
    assert d.results[1].passed is True and d.outcome is Outcome.DEFER


def test_room_uses_the_declared_share_of_lots():
    cap = int(MAX_SHARE_OF_LOTS.value * 100)          # 15 points on 100 lots
    assert _run(total_lots=100, existing_connectors=cap - 1).outcome is Outcome.ACCEPT
    full = _run(total_lots=100, existing_connectors=cap)
    assert full.outcome is Outcome.REJECT and full.failing_rules == ["R03"]
    assert full.results[2].detail == "Room for 0 more points within 15% of 100 lots."


def test_zero_existing_connectors_is_a_fact_not_a_gap():
    assert _run(existing_connectors=0).outcome is Outcome.ACCEPT


def test_no_supply_is_not_treated_as_idle():
    d = _run(supply_state="no_supply", utilisation=None, existing_connectors=0)
    assert d.outcome is Outcome.ACCEPT


def test_evaluate_needs_an_on_fail_for_every_rule():
    with pytest.raises(ValueError, match="on_fail"):
        R.evaluate("hdb:X", _facts(), RULES, {})


def test_reasons_survive_a_round_trip_through_the_contract(screened):
    for d in screened[0]:
        assert Decision.model_validate_json(d.model_dump_json()) == d
        assert all(r.detail for r in d.results)


def test_site_facts_leave_unknowns_out():
    site = next(s for s in S.sites if s.site_id == "SYN-S-27")   # hawker, no lots
    ind = next(i for i in S.indicators if i.site_id == site.site_id)
    facts = R.site_facts(site, None, ind, {"amenities_nearby": 0, "land_use": None})
    assert "total_lots" not in facts and "utilisation" not in facts
    assert "land_use" not in facts and facts["amenities_nearby"] == 0
    assert facts["existing_connectors"] == 0 and facts["supply_state"] == "no_supply"
    assert set(facts) <= set(R.FACTS)
    with pytest.raises(ValueError):
        R.site_facts(site, None, S.indicators[0], {})


# 3.3 · screening --------------------------------------------------------------------------

def test_funnel_counts_every_outcome(screened):
    decisions, funnel = screened
    assert funnel["sites"] == 30
    assert sum(funnel[o.value] for o in Outcome) == 30
    assert (funnel["accept"], funnel["conditional"], funnel["reject"], funnel["defer"]) == \
        (23, 2, 2, 3)
    assert funnel["failed:R03"] == 1 and funnel["unevaluated:R01"] == 3


def test_unmeasured_site_is_deferred_not_dropped():
    site = S.sites[0]
    decisions, funnel = screen_sites([site], S.car_parks, [], {}, RULES, ON_FAIL, "base")
    assert decisions[0].outcome is Outcome.DEFER
    assert decisions[0].unevaluated_rules == ["R04"] and decisions[0].scenario_id == "base"


def test_screening_respects_the_supply_contract():
    idle = SiteIndicators(site_id="SYN-S-01", window_start="a", window_end="b",
                          supply_state=SupplyState.SUPPLY_IDLE, active_connectors=4,
                          utilisation=0.01)
    decisions, _ = screen_sites([S.sites[0]], S.car_parks, [idle], {}, RULES, ON_FAIL)
    assert decisions[0].outcome is Outcome.REJECT and decisions[0].failing_rules == ["R04"]


class _Cursor:
    def __init__(self, log: list[tuple[str, Any]]) -> None:
        self.log = log

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def executemany(self, query: str, rows: list[dict[str, Any]]) -> None:
        for name in re.findall(r"%\((\w+)\)s", query):
            assert all(name in row for row in rows), name
        self.log.append((query, rows))


class _Conn:
    def __init__(self) -> None:
        self.log: list[tuple[str, Any]] = []

    def cursor(self) -> _Cursor:
        return _Cursor(self.log)


def test_write_decisions_stores_observed_baseline_and_every_result(screened):
    conn = _Conn()
    counts = write_decisions(conn, RULES, ON_FAIL, screened[0])  # type: ignore[arg-type]
    assert counts == {"rule": 5, "decision": 30, "rule_result": 150}
    rows = conn.log[1][1]
    assert {r["scenario_id"] for r in rows} == {"observed"}
    rule_rows = conn.log[0][1]
    assert {r["on_fail"] for r in rule_rows} == {"reject", "conditional"}


def test_screen_needs_a_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        screen()
