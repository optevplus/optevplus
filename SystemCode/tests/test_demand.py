"""Demand inference (§4.2 step 2) on optev.sample, scored against its answer key `truth()`.
The sample covers two weekdays, so every served site has 24 `wd` bins and no `we` bins. The
live test runs only when DATABASE_URL is in the environment and is rolled back."""

import os
from datetime import datetime, timedelta

import pytest

from optev import sample
from optev.analysis import demand as D
from optev.analysis import indicators as I
from optev.assumptions import MEAN_SESSION_HOURS, RELIABLE_UP_TO
from optev.contracts import DemandEstimate, SiteIndicators
from optev.contracts.enums import EstimateKind, SupplyState
from optev.sample import generate

START = datetime(2026, 10, 1, tzinfo=I.SGT)
END = START + timedelta(hours=48)
S = sample.load()
READINGS = sample.connector_readings()
TRUTH = sample.truth()["sites"]
INDICATORS = I.compute_indicators(S.sites, S.near, S.connectors, READINGS, START, END)
OCCUPANCY = I.compute_occupancy_by_bin(S.sites, S.near, S.connectors, READINGS, START, END)
SERVED = {i.site_id for i in INDICATORS if i.supply_state in D.MEASURED}


def _all_rows() -> dict[str, DemandEstimate]:
    return {e.site_id: e for e in D.infer_demand(INDICATORS, OCCUPANCY) if e.time_bin == "all"}


def test_erlang_b_known_values_and_the_sample_generator():
    assert D.erlang_b(0, 3.0) == 1.0
    assert D.erlang_b(1, 2.0) == pytest.approx(2 / 3)
    assert D.erlang_b(2, 1.0) == pytest.approx(0.2)
    for c in range(1, 9):
        for a in (0.1, 1.0, 4.0, 12.0):
            assert D.erlang_b(c, a) == pytest.approx(generate.erlang_b(c, a))
    with pytest.raises(ValueError):
        D.erlang_b(2, -1.0)


@pytest.mark.parametrize("c", range(1, 9))
def test_invert_occupancy_round_trips_and_rises(c):
    previous = -1.0
    for occ in (0.0, 0.05, 0.3, 0.6, 0.9, RELIABLE_UP_TO.value, 0.99):
        rate = D.invert_occupancy(c, occ)
        assert rate > previous
        assert D._occupancy(c, rate * MEAN_SESSION_HOURS.value) == pytest.approx(occ, abs=1e-9)
        previous = rate
    assert D.invert_occupancy(c, 0.0) == 0.0


def test_invert_occupancy_rejects_what_it_cannot_invert():
    for c, occ in ((0, 0.5), (2, 1.0), (2, -0.1)):
        with pytest.raises(ValueError):
            D.invert_occupancy(c, occ)


def test_every_served_site_gets_its_bins_and_all_and_no_supply_gets_nothing():
    rows = D.infer_demand(INDICATORS, OCCUPANCY)
    by_site: dict[str, set[str]] = {}
    for e in rows:
        by_site.setdefault(e.site_id, set()).add(e.time_bin)
    assert set(by_site) == SERVED and SERVED
    weekdays = {f"wd-{h:02d}" for h in range(24)}
    assert all(bins == weekdays | {"all"} for bins in by_site.values())


def test_bins_at_the_reliable_limit_are_lower_bounds_reported_at_the_limit():
    cap = RELIABLE_UP_TO.value
    ind = {i.site_id: i for i in INDICATORS}
    for e in D.infer_demand(INDICATORS, OCCUPANCY):
        if e.time_bin == "all":
            continue
        occ = OCCUPANCY[e.site_id][e.time_bin]
        assert (e.kind == EstimateKind.LOWER_BOUND) == (occ >= cap), (e.site_id, e.time_bin)
        want = D.invert_occupancy(ind[e.site_id].active_connectors, min(occ, cap))
        assert e.arrivals_per_hour == pytest.approx(want)


def test_all_is_the_daily_average_of_bins_and_a_bound_only_when_saturated():
    rows = D.infer_demand(INDICATORS, OCCUPANCY)
    rows_all = _all_rows()
    for site in SERVED:
        bins = [e.arrivals_per_hour for e in rows if e.site_id == site and e.time_bin != "all"]
        assert rows_all[site].arrivals_per_hour == pytest.approx(sum(bins) / len(bins))
    bounded = {s for s, e in rows_all.items() if e.kind == EstimateKind.LOWER_BOUND}
    assert bounded == {"SYN-S-04"}
    assert rows_all["SYN-S-04"].arrivals_per_hour < TRUTH["SYN-S-04"]["true_arrivals_per_hour"]


def test_all_weights_weekdays_and_weekends_as_section_3_4():
    ind = SiteIndicators(site_id="x", window_start="", window_end="", active_connectors=2,
                         supply_state=SupplyState.SUPPLY_ACTIVE, utilisation=0.5)
    occ = {"wd-09": 0.2, "we-09": 0.6, "all": 0.99}
    rows = {e.time_bin: e.arrivals_per_hour for e in D.infer_demand([ind], {"x": occ})}
    wd, we = D.invert_occupancy(2, 0.2), D.invert_occupancy(2, 0.6)
    assert rows["all"] == pytest.approx((5 * wd + 2 * we) / 7)


def test_unobserved_and_missing_sites_are_skipped():
    window = {"window_start": "", "window_end": ""}
    unobserved = SiteIndicators(site_id="u", supply_state=SupplyState.UNOBSERVED,
                                active_connectors=3, **window)
    absent = SiteIndicators(site_id="a", supply_state=SupplyState.SUPPLY_ACTIVE,
                            active_connectors=3, utilisation=0.4, **window)
    assert D.infer_demand([unobserved, absent], {"u": {"wd-01": 0.5}}) == []


def test_per_bin_recovers_truth_better_than_the_whole_window():
    """§6: MAPE against known demand, baseline the whole-window inversion in the sample's
    `estimates`. Measured here: about 14% per bin against 28% whole window (spec 012)."""
    rows_all = _all_rows()
    baseline = {e.site_id: e.arrivals_per_hour for e in S.estimates}
    ind = {i.site_id: i for i in INDICATORS}
    below = [s for s in SERVED if (ind[s].utilisation or 0) < RELIABLE_UP_TO.value]
    assert len(below) == len(SERVED) - 1

    def mape(estimate: dict[str, float]) -> float:
        errors = [abs(estimate[s] - TRUTH[s]["true_arrivals_per_hour"])
                  / TRUTH[s]["true_arrivals_per_hour"] for s in below]
        return sum(errors) / len(errors)

    per_bin = mape({s: e.arrivals_per_hour for s, e in rows_all.items()})
    assert per_bin < 0.2
    assert per_bin < mape(baseline) / 1.5


live = pytest.mark.skipif(not os.environ.get("DATABASE_URL"),
                          reason="DATABASE_URL not in environment")


@live
def test_write_estimates_upserts_with_method_queueing():
    import psycopg

    rows = D.infer_demand(INDICATORS, OCCUPANCY)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        try:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO candidate_site (site_id, kind, geom) VALUES"
                    " (%s, %s, ST_SetSRID(ST_MakePoint(103.9, 1.35), 4326))",
                    [(s.site_id, s.kind.value) for s in S.sites])
            for _ in range(2):
                assert D.write_estimates(conn, rows) == len(rows)
            got = conn.execute(
                "SELECT count(*), count(*) FILTER (WHERE method = 'queueing')"
                " FROM demand_estimate WHERE site_id LIKE 'SYN-%%'").fetchone()
            assert got == (len(rows), len(rows))
        finally:
            conn.rollback()
