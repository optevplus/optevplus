"""Rules engine (#18) and eligibility screening (#19), SYSTEM_DESIGN.md §4.4, on optev.sample."""

from datetime import datetime, timedelta

import pytest

from optev.contracts import Decision, Outcome, Rule, RuleResult, RuleSource, SupplyState
from optev.reasoning import rules as R
from optev.sample import load

S = load()
RULES, ON_FAIL = R.load_register()
SITES = {s.site_id: s for s in S.sites}
CAR_PARKS = {cp.car_park_id: cp for cp in S.car_parks}
INDICATORS = {i.site_id: i for i in S.indicators}
SAMPLE = {d.site_id: d for d in S.decisions}


def _facts(site_id: str) -> dict[str, object]:
    site = SITES[site_id]
    return R.site_facts(site, CAR_PARKS.get(site.car_park_id or ""), INDICATORS[site_id], {})


def _screen(**overrides):
    args = dict(sites=S.sites, car_parks=S.car_parks, indicators=S.indicators, context={},
                rules=RULES, on_fail=ON_FAIL)
    return R.screen(**(args | overrides))


# Facts --------------------------------------------------------------------------------

def test_site_facts_carry_site_car_park_indicators_and_context():
    site = SITES["SYN-S-06"]
    facts = R.site_facts(site, CAR_PARKS["SYN-CP-06"], INDICATORS["SYN-S-06"],
                         {"amenities_nearby": 2, "nearest_point_m": 140.0, "other": 1})
    assert facts["total_lots"] == 380 and facts["car_park_type"] == "BASEMENT CAR PARK"
    assert facts["supply_state"] == INDICATORS["SYN-S-06"].supply_state
    assert facts["amenities_nearby"] == 2 and facts["nearest_point_m"] == 140.0
    assert "other" not in facts and set(facts) <= R.FACTS


def test_missing_values_are_absent_never_zero():
    facts = _facts("SYN-S-27")  # hawker centre: no lots, no chargers
    assert "total_lots" not in facts and "car_park_type" not in facts
    assert "utilisation" not in facts  # no supply: utilisation is None, not 0 (invariant 2)
    assert facts["supply_state"] == SupplyState.NO_SUPPLY


def test_indicators_for_another_site_are_refused():
    with pytest.raises(ValueError, match="given for site"):
        R.site_facts(SITES["SYN-S-01"], None, INDICATORS["SYN-S-02"], {})


# Engine -------------------------------------------------------------------------------

def test_every_register_rule_has_a_check():
    assert {r.rule_id for r in RULES} <= set(R.CHECKS)


def test_room_is_derived_by_forward_chaining():
    facts = _facts("SYN-S-01")
    known = R.derive(facts)
    assert known["room"] == 89  # floor(0.15 * 620) - 4
    assert "room" not in facts  # inputs untouched
    assert "room" not in R.derive(_facts("SYN-S-27"))  # needs total_lots


def test_rule_results_match_the_sample_for_every_shared_rule():
    # the sample has no reason text for a basement; R02 records one, so compare its verdict only
    def key(r):
        return (r.rule_id, r.passed, None if r.rule_id == "R02" and r.passed is False else r.detail)

    for site_id, want in SAMPLE.items():
        got = R.evaluate(site_id, _facts(site_id), RULES, ON_FAIL)
        expected = [key(r) for r in want.results if r.rule_id in R.CHECKS]
        shared = [key(r) for r in got.results if r.rule_id in {e[0] for e in expected}]
        assert shared == expected, site_id


def test_every_rule_is_evaluated_in_register_order():
    d = R.evaluate("SYN-S-13", _facts("SYN-S-13"), RULES, ON_FAIL)
    assert [r.rule_id for r in d.results] == [r.rule_id for r in RULES]
    assert d.failing_rules == ["R03"]  # later rules still ran after the failure


def test_a_missing_fact_defers_and_never_rejects():
    d = R.evaluate("SYN-S-27", _facts("SYN-S-27"), RULES, ON_FAIL)
    assert d.outcome is Outcome.DEFER  # a gap outranks the conditional R06 failure
    assert d.unevaluated_rules == ["R01", "R03"] and d.failing_rules == ["R06"]
    assert d.results[0].detail == "total_lots missing"


def test_r05_defers_a_site_outside_every_planning_area():
    facts = {k: v for k, v in _facts("SYN-S-01").items() if k != "planning_area"}
    d = R.evaluate("SYN-S-01", facts, RULES, ON_FAIL)
    r05 = next(r for r in d.results if r.rule_id == "R05")
    assert (r05.passed, r05.detail, d.outcome) == (None, "planning_area missing", Outcome.DEFER)


def _result(d, rule_id):
    return next(r for r in d.results if r.rule_id == rule_id)


def test_r02_makes_a_basement_car_park_conditional():
    d = R.evaluate("SYN-S-11", _facts("SYN-S-11"), RULES, ON_FAIL)  # basement, chargers, room
    assert d.outcome is Outcome.CONDITIONAL and d.failing_rules == ["R02"]
    assert _result(d, "R02").detail == BASEMENT


BASEMENT = "basement: confirm sprinklers and EV isolation switch"


@pytest.mark.parametrize(("site_id", "car_park_type", "want"), [
    ("SYN-S-01", "MULTI-STOREY CAR PARK", (True, None)),
    ("SYN-S-01", "BASEMENT CAR PARK", (False, BASEMENT)),
    ("SYN-S-01", "Basement car park", (False, BASEMENT)),
    ("SYN-S-01", None, (None, "car_park_type missing")),     # e.g. URA: type unknown -> defer
    ("SYN-S-27", None, (True, "not a car park")),             # hawker centre
])
def test_r02_by_site_kind_and_type(site_id, car_park_type, want):
    facts = {k: v for k, v in _facts(site_id).items() if k != "car_park_type"}
    if car_park_type is not None:
        facts["car_park_type"] = car_park_type
    r02 = _result(R.evaluate(site_id, facts, RULES, ON_FAIL), "R02")
    assert (r02.passed, r02.detail) == want


def test_a_car_park_of_unknown_type_defers_rather_than_passing():
    facts = {k: v for k, v in _facts("SYN-S-01").items() if k != "car_park_type"}
    assert R.evaluate("SYN-S-01", facts, RULES, ON_FAIL).outcome is Outcome.DEFER


def test_r06_is_conditional_where_no_charger_runs_yet():
    d = R.evaluate("SYN-S-07", _facts("SYN-S-07"), RULES, ON_FAIL)  # room, no chargers
    assert d.outcome is Outcome.CONDITIONAL and d.failing_rules == ["R06"]
    assert d.results[-1].detail == "electrical capacity to be confirmed"
    assert R.evaluate("SYN-S-01", _facts("SYN-S-01"), RULES, ON_FAIL).outcome is Outcome.ACCEPT


@pytest.mark.parametrize(("results", "want"), [
    ([True, True], Outcome.ACCEPT),
    ([True, None], Outcome.DEFER),
    ([None, False], Outcome.DEFER),            # conditional failure + gap: gap first
    ([True, False], Outcome.CONDITIONAL),
    ([False, None], Outcome.REJECT),           # reject beats a gap
    ([False, False], Outcome.REJECT),
])
def test_outcome_policy_order(results, want):
    on_fail = {"A": Outcome.REJECT, "B": Outcome.CONDITIONAL}
    rs = [RuleResult(rule_id=k, passed=p) for k, p in zip("AB", results, strict=True)]
    assert R.outcome(rs, on_fail) is want


def test_a_conditional_rule_gives_conditional(monkeypatch):
    monkeypatch.setitem(R.CHECKS, "T1", lambda f: (False, "needs review"))
    t1 = Rule(rule_id="T1", condition="test", source=RuleSource.PROJECT_ASSUMPTION,
              source_ref="asm-test", required_facts=["kind"], explanation_template="x")
    d = R.evaluate("SYN-S-01", _facts("SYN-S-01"), [*RULES, t1],
                   ON_FAIL | {"T1": Outcome.CONDITIONAL})
    assert d.outcome is Outcome.CONDITIONAL and d.results[-1].detail == "needs review"


def test_a_rule_without_a_check_is_an_error_not_a_defer():
    ghost = RULES[0].model_copy(update={"rule_id": "R99"})
    with pytest.raises(ValueError, match="no check"):
        R.evaluate("SYN-S-01", _facts("SYN-S-01"), [ghost], {"R99": Outcome.REJECT})


def test_a_failing_rule_needs_an_on_fail():
    with pytest.raises(ValueError, match="no on_fail"):
        R.outcome([RuleResult(rule_id="R03", passed=False)], {})


def test_reasons_survive_a_round_trip_through_the_contract():
    d = R.evaluate("SYN-S-13", _facts("SYN-S-13"), RULES, ON_FAIL, "base")
    assert Decision.model_validate_json(d.model_dump_json()) == d
    assert d.scenario_id == "base" and _result(d, "R03").detail == "room 0"


# Screening ----------------------------------------------------------------------------

def test_screening_reports_the_funnel_over_every_site():
    decisions, funnel = _screen()
    assert len(decisions) == len(S.sites)
    assert funnel == {Outcome.ACCEPT: 8, Outcome.REJECT: 2, Outcome.DEFER: 3,
                      Outcome.CONDITIONAL: 17}
    assert all(funnel.values())  # all four outcomes appear


def test_screening_agrees_with_the_sample_wherever_the_rule_sets_agree():
    # the sample ran R01-R05 but not R06; wherever R06 passed, outcomes must match exactly
    decisions, _ = _screen()
    compared = 0
    for d in decisions:
        if _result(d, "R06").passed:
            assert d.outcome == SAMPLE[d.site_id].outcome, d.site_id
            compared += 1
    assert compared == 11  # every site with chargers running
    by_site = {d.site_id: d.outcome for d in decisions}
    assert {s for s, o in by_site.items() if o is Outcome.REJECT} == {"SYN-S-13", "SYN-S-14"}


def test_screening_uses_the_latest_indicators_window():
    ind = INDICATORS["SYN-S-01"]
    later = datetime.fromisoformat(ind.window_end) + timedelta(days=2)
    newer = ind.model_copy(update={"window_start": ind.window_end,
                                   "window_end": later.isoformat(),
                                   "supply_state": SupplyState.SUPPLY_IDLE})
    decisions, _ = _screen(indicators=[newer, *S.indicators])
    assert next(d for d in decisions if d.site_id == "SYN-S-01").outcome is Outcome.REJECT


def test_a_site_without_indicators_defers():
    decisions, funnel = _screen(indicators=[i for i in S.indicators if i.site_id != "SYN-S-01"])
    d = next(d for d in decisions if d.site_id == "SYN-S-01")
    assert d.outcome is Outcome.DEFER and _result(d, "R04").detail == "supply_state missing"
    assert funnel[Outcome.DEFER] == 4


def test_screening_passes_the_scenario_through():
    decisions, _ = _screen(scenario_id="base")
    assert {d.scenario_id for d in decisions} == {"base"}


def test_the_allocators_input_is_the_screened_set():
    decisions, funnel = _screen()
    eligible = {d.site_id for d in decisions if d.outcome in (Outcome.ACCEPT, Outcome.CONDITIONAL)}
    assert len(eligible) == funnel[Outcome.ACCEPT] + funnel[Outcome.CONDITIONAL]
    assert not eligible & {"SYN-S-13", "SYN-S-14", "SYN-S-27", "SYN-S-28", "SYN-S-30"}


# Writing ------------------------------------------------------------------------------

class FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[tuple[object, ...]]]] = []

    def executemany(self, sql: str, rows: list[tuple[object, ...]]) -> None:
        for row in rows:
            assert sql.count("%s") == len(row), sql
        self.calls.append((sql, rows))


def test_write_decisions_replaces_results_per_site_and_scenario():
    decisions, _ = _screen()
    cur = FakeCursor()
    written = R.write_decisions(cur, RULES, ON_FAIL, decisions)  # type: ignore[arg-type]
    assert written == {"rule": 6, "decision": 30, "rule_result": 180}
    assert [sql for sql, _ in cur.calls] == [
        R.UPSERT_RULE, R.UPSERT_DECISION, R.CLEAR_RESULTS, R.INSERT_RESULT]
    rules_rows, decision_rows, cleared, results = (rows for _, rows in cur.calls)
    assert rules_rows[0][4] == ["total_lots"] and rules_rows[0][6] == "reject"
    assert {row[1] for row in decision_rows} == {"observed"}  # no scenario -> 'observed'
    assert cleared == [row[:2] for row in decision_rows]
    assert ("SYN-S-13", "observed", "R03", False, "room 0") in results
    assert all("{" not in sql for sql, _ in cur.calls)


def test_write_decisions_keeps_the_scenario():
    decisions, _ = _screen(scenario_id="base")
    cur = FakeCursor()
    R.write_decisions(cur, RULES, ON_FAIL, decisions[:1])  # type: ignore[arg-type]
    assert cur.calls[1][1] == [(decisions[0].site_id, "base", "accept")]


# Screening the database (fake connection fed from the sample) ----------------------------

def _table_rows() -> dict[str, list[dict[str, object]]]:
    def flat(model, **extra):  # a table row: coordinates split, windows as timestamps
        row = model.model_dump(mode="json")
        if "coord" in row:
            row |= row.pop("coord")
        return row | extra
    return {
        R.READ_SITES: [flat(s) for s in S.sites],
        R.READ_CAR_PARKS: [flat(c) for c in S.car_parks],
        R.READ_INDICATORS: [flat(i, window_start=datetime.fromisoformat(i.window_start),
                                 window_end=datetime.fromisoformat(i.window_end))
                            for i in S.indicators],
        R.READ_CONTEXT: [{"site_id": s.site_id, "land_use": None, "amenities_nearby": 0,
                          "nearest_point_m": None} for s in S.sites],
    }


class FakeConnection:
    def __init__(self) -> None:
        self.rows, self.written, self.committed = _table_rows(), [], False

    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def cursor(self): return self
    def execute(self, sql, params=None): return iter(self.rows[sql])
    def executemany(self, sql, rows): self.written.append((sql, rows))
    def commit(self): self.committed = True


def test_screen_all_reads_the_tables_and_writes_decisions(monkeypatch):
    import psycopg

    conn = FakeConnection()
    monkeypatch.setattr(psycopg, "connect", lambda url, row_factory=None: conn)
    funnel = R.screen_all("postgresql://fake", write=True)
    assert funnel == _screen()[1] and all(funnel.values())
    assert conn.committed and [sql for sql, _ in conn.written][0] == R.UPSERT_RULE


def test_screen_all_dry_run_writes_nothing(monkeypatch):
    import psycopg

    conn = FakeConnection()
    monkeypatch.setattr(psycopg, "connect", lambda url, row_factory=None: conn)
    R.screen_all("postgresql://fake", "base", write=False)
    assert conn.written == [] and not conn.committed


def test_rows_skip_bad_rows_and_convert_timestamps():
    ind = S.indicators[0].model_dump(mode="json")
    good = ind | {"window_end": datetime.fromisoformat(ind["window_end"])}
    bad = ind | {"site_id": "SYN-BAD", "supply_state": "busy"}
    rows = R._rows(R.SiteIndicators, [good, bad])
    assert [r.site_id for r in rows] == [ind["site_id"]]
    assert rows[0].window_end == datetime.fromisoformat(ind["window_end"]).isoformat()


def test_cli_needs_a_database_and_passes_dry_run(monkeypatch, tmp_path, capsys):
    from optev.reasoning import __main__ as cli

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(cli, "ENV_FILE", tmp_path / ".env")  # no .env there
    assert cli.main(["screen"]) == 1
    seen = {}

    def fake(url, scenario, write):
        seen.update(url=url, scenario=scenario, write=write)
        return _screen()[1]

    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(cli, "screen_all", fake)
    assert cli.main(["screen", "--scenario", "base", "--dry-run"]) == 0
    assert seen == {"url": "postgresql://fake", "scenario": "base", "write": False}
    out = capsys.readouterr().out
    assert "screened 30 sites (base)" in out and "conditional" in out
