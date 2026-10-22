"""Demand page (#33): indicators, patterns and estimates, every figure labelled, on optev.sample."""

from dataclasses import replace
from pathlib import Path

from optev.app import data as D
from optev.app import demand_view as V
from optev.contracts import DemandEstimate
from optev.contracts.enums import EstimateKind, SupplyState

DATA = D.from_sample()
ROWS = {r["site_id"]: r for r in V.demand_table(DATA)}
STATE = {i.site_id: i.supply_state for i in DATA.indicators}


def test_figure_marks_a_lower_bound_at_least():
    point = DemandEstimate(site_id="x", time_bin="all", arrivals_per_hour=2.5,
                           kind=EstimateKind.POINT)
    bound = point.model_copy(update={"kind": EstimateKind.LOWER_BOUND})
    assert V.figure(point) == "2.50"
    assert V.figure(bound) == "at least 2.50"
    assert V.figure(None) is None


def test_sample_extends_app_data_with_bins_and_patterns():
    assert DATA.profiles and all(e.time_bin != "all" for e in DATA.profiles)
    served = {i.site_id for i in DATA.indicators if i.supply_state == SupplyState.SUPPLY_ACTIVE}
    assert served <= {e.site_id for e in DATA.profiles}
    assert set(DATA.patterns) <= {e.site_id for e in DATA.profiles}
    assert set(DATA.pattern_labels) == set(DATA.patterns.values())
    assert [e.time_bin for e in DATA.profiles if e.site_id == "SYN-S-01"] == [
        f"wd-{h:02d}" for h in range(24)]  # two weekdays: no weekend bins


def test_every_figure_column_says_observed_or_inferred():
    plain = {"site_id", "kind", "planning_area", "lower_bound", "method"}
    for row in ROWS.values():
        for col in set(row) - plain:
            assert col.endswith(("(observed)", "(inferred)")), col
    assert len(ROWS) == len(DATA.sites)


def test_no_supply_keeps_utilisation_none_and_lower_bounds_read_at_least():
    for site_id, row in ROWS.items():
        if STATE.get(site_id) == SupplyState.NO_SUPPLY:
            assert row["utilisation (observed)"] is None
            assert row["pattern (inferred)"] is None
        if row["lower_bound"]:
            assert row["demand_per_h (inferred)"].startswith("at least ")
    assert any(r["lower_bound"] for r in ROWS.values())


def test_table_filters_by_area():
    rows = V.demand_table(DATA, "PR")
    assert rows and all(r["planning_area"] == "PR" for r in rows)


def test_supply_counts_has_every_state():
    counts = V.supply_counts(DATA)
    assert set(counts) == {s.value for s in SupplyState}
    assert sum(counts.values()) == len(DATA.indicators)


def test_profile_is_hourly_and_marks_saturated_hours():
    hours = V.profile(DATA, "SYN-S-01")
    assert [h["hour"] for h in hours] == list(range(24))
    assert {h["day"] for h in hours} == {"weekday"}
    bounded = [h for h in hours if h["lower_bound"]]
    assert bounded and all(h["reads as"].startswith("at least ") for h in bounded)
    no_supply = next(s for s, st in STATE.items() if st == SupplyState.NO_SUPPLY)
    assert V.profile(DATA, no_supply) == []


def test_pattern_rows_group_sites_by_cluster():
    rows = V.pattern_rows(DATA)
    assert [r["cluster"] for r in rows] == sorted(set(DATA.patterns.values()))
    assert sum(r["sites"] for r in rows) == len(DATA.patterns)
    assert all(r["pattern (inferred)"] == DATA.pattern_labels[r["cluster"]] for r in rows)
    assert V.pattern_rows(replace(DATA, patterns={})) == []


def test_demand_page_renders_on_the_sample(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(D, "ENV_FILE", tmp_path / ".env")
    page = Path(D.__file__).with_name("pages") / "4_Demand.py"
    at = AppTest.from_file(str(page), default_timeout=60).run()
    assert not at.exception
    assert len(at.metric) == 6  # four supply states, then one site's demand and utilisation
    assert len(at.dataframe) >= 3  # sites, patterns, one site's hours
