"""Site indicators (§4.2 step 1) on optev.sample, whose generator measures the same way, so
the sample's indicators are an independent answer. The live test runs only when DATABASE_URL
is in the environment (`uv run --env-file .env pytest`) and is rolled back."""

import os
from datetime import datetime, timedelta

import pytest

from optev import sample
from optev.analysis import indicators as I
from optev.assumptions import MATCH_THRESHOLDS_M, SNAPSHOT_MINUTES
from optev.contracts import CandidateSite, Connector, ConnectorReading, SiteIndicators
from optev.contracts.enums import SupplyState

SGT = I.SGT
START = datetime(2026, 10, 1, tzinfo=SGT)
END = START + timedelta(hours=48)
S = sample.load()
READINGS = sample.connector_readings()


def _computed() -> dict[str, SiteIndicators]:
    out = I.compute_indicators(S.sites, S.near, S.connectors, READINGS, START, END)
    return {i.site_id: i for i in out}


def test_reproduces_the_sample_indicators():
    got = _computed()
    assert set(got) == {s.site_id for s in S.sites}
    for want in S.indicators:
        g = got[want.site_id]
        assert g.supply_state == want.supply_state, want.site_id
        assert g.active_connectors == want.active_connectors, want.site_id
        assert g.window_start == want.window_start and g.window_end == want.window_end
        for field in ("utilisation", "saturated_fraction", "observation_coverage"):
            w, v = getattr(want, field), getattr(g, field)
            assert (w is None) == (v is None), (want.site_id, field)
            if w is not None:
                assert v == pytest.approx(w, abs=5e-5), (want.site_id, field)


def test_never_active_connector_is_not_counted():
    inactive = [c for c in S.connectors if not c.ever_active]
    assert inactive
    station = inactive[0].station_id
    site = next(n["site_id"] for n in S.near if n["station_id"] == station)
    active = sum(1 for c in S.connectors if c.station_id == station and c.ever_active)
    assert _computed()[site].active_connectors == active


def test_feed_gap_lowers_coverage_and_no_charger_sites_have_no_utilisation():
    got = _computed()
    assert got["SYN-S-05"].observation_coverage == pytest.approx(92 / 96)
    assert got["SYN-S-14"].supply_state == SupplyState.SUPPLY_IDLE
    no_supply = [i for i in got.values() if i.supply_state == SupplyState.NO_SUPPLY]
    assert no_supply and all(i.utilisation is None and i.active_connectors == 0
                             for i in no_supply)


def _one_site(statuses_by_slot: list[list[str]], threshold_m: int = 50
              ) -> tuple[list[CandidateSite], list[dict], list[Connector], list[ConnectorReading]]:
    site = S.sites[0].model_copy(update={"site_id": "SYN-T"})
    near = [{"station_id": "SYN-T-ST", "site_id": "SYN-T", "distance_m": 0.0,
             "threshold_m": threshold_m}]
    n = len(statuses_by_slot[0]) if statuses_by_slot else 1
    conns = [Connector(connector_id=f"SYN-T-{k}", station_id="SYN-T-ST", ever_active=True)
             for k in range(n)]
    readings = [
        ConnectorReading(connector_id=f"SYN-T-{k}", status=st,
                         collected_ts=START + i * I.SLOT + timedelta(seconds=-90 if k else 90))
        for i, row in enumerate(statuses_by_slot) for k, st in enumerate(row)
    ]
    return [site], near, conns, readings


def test_low_coverage_is_unobserved_not_zero():
    end = START + 10 * I.SLOT
    [got] = I.compute_indicators(*_one_site([["available", "available"]] * 4), START, end)
    assert got.supply_state == SupplyState.UNOBSERVED
    assert got.utilisation is None and got.observation_coverage == pytest.approx(0.4)


def test_all_unavailable_is_unobserved():
    end = START + 4 * I.SLOT
    [got] = I.compute_indicators(*_one_site([["unavailable"]] * 4), START, end)
    assert got.supply_state == SupplyState.UNOBSERVED and got.observation_coverage == 1.0


def test_unavailable_is_excluded_and_saturation_counted():
    rows = [["occupied", "unavailable"], ["occupied", "available"]]
    [got] = I.compute_indicators(*_one_site(rows), START, START + 2 * I.SLOT)
    assert got.utilisation == pytest.approx((1.0 + 0.5) / 2)
    assert got.saturated_fraction == pytest.approx(0.5)
    assert got.supply_state == SupplyState.SUPPLY_ACTIVE


def test_station_beyond_100_m_is_not_matched():
    assert I.MATCH_WITHIN_M in MATCH_THRESHOLDS_M
    [got] = I.compute_indicators(*_one_site([["occupied"]], threshold_m=200),
                                 START, START + I.SLOT)
    assert got.supply_state == SupplyState.NO_SUPPLY


def _shared_station(far_m: float) -> list[SiteIndicators]:
    """One station within 100 m of two sites: SYN-T at 30 m and SYN-U at `far_m`."""
    sites, near, conns, readings = _one_site([["occupied"]])
    sites.append(sites[0].model_copy(update={"site_id": "SYN-U"}))
    near = [{**near[0], "distance_m": 30.0},
            {**near[0], "site_id": "SYN-U", "distance_m": far_m, "threshold_m": 100}]
    return I.compute_indicators(sites, near, conns, readings, START, START + I.SLOT)


def test_station_near_two_sites_counts_at_its_nearest_only():
    t, u = _shared_station(far_m=80.0)
    assert t.active_connectors == 1 and t.utilisation == 1.0
    assert u.supply_state == SupplyState.NO_SUPPLY and u.active_connectors == 0


def test_station_equally_near_two_sites_counts_at_the_lower_site_id():
    t, u = _shared_station(far_m=30.0)
    assert t.active_connectors == 1 and u.active_connectors == 0


def test_slots_and_bins():
    assert timedelta(minutes=SNAPSHOT_MINUTES) == I.SLOT
    assert I.snapshot_slot(START - timedelta(seconds=100)) == START
    assert I.snapshot_slot(START + timedelta(seconds=100)) == START
    week = datetime(2026, 10, 7, 14, tzinfo=SGT), datetime(2026, 10, 14, 11, tzinfo=SGT)
    assert I.expected_slots(*week) == 330
    assert I.time_bin(datetime(2026, 10, 10, 23, 30, tzinfo=SGT)) == "we-23"  # Saturday
    assert I.time_bin(datetime(2026, 10, 12, 0, 0, tzinfo=SGT)) == "wd-00"


def test_occupancy_by_bin_on_the_sample():
    bins = I.compute_occupancy_by_bin(S.sites, S.near, S.connectors, READINGS, START, END)
    got = _computed()
    measured = {k for k, v in got.items() if v.supply_state in I.MEASURED}
    assert set(bins) == measured
    for site, per_bin in bins.items():
        hourly = {b: v for b, v in per_bin.items() if b != "all"}
        assert set(hourly) == {f"wd-{h:02d}" for h in range(24)}  # 1-2 Oct are weekdays
        assert all(0 <= v <= 1 for v in per_bin.values())
        assert per_bin["all"] == pytest.approx(sum(hourly.values()) / 24), site


def test_all_bin_weights_weekdays_and_weekends():
    sat = datetime(2026, 10, 10, 9, tzinfo=SGT)
    mon = datetime(2026, 10, 12, 9, tzinfo=SGT)
    counts: I.Counts = {"x": {sat: (1, 0), mon: (0, 1)}}
    ind = SiteIndicators(site_id="x", window_start="", window_end="",
                         supply_state=SupplyState.SUPPLY_ACTIVE, utilisation=0.5)
    per_bin = I._bins([ind], counts)["x"]
    assert per_bin == {"wd-09": 0.0, "we-09": 1.0, "all": pytest.approx(2 / 7)}


live = pytest.mark.skipif(not os.environ.get("DATABASE_URL"),
                          reason="DATABASE_URL not in environment")


@live
def test_postgres_counts_match_and_upsert_is_rerunnable():
    import psycopg

    from optev.ingest import collect

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        try:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO station (station_id, geom) VALUES"
                    " (%s, ST_SetSRID(ST_MakePoint(103.9, 1.35), 4326))",
                    [(st.station_id,) for st in S.stations])
                cur.executemany(
                    "INSERT INTO connector (connector_id, station_id, ever_active)"
                    " VALUES (%s, %s, %s)",
                    [(c.connector_id, c.station_id, c.ever_active) for c in S.connectors])
                cur.executemany(
                    "INSERT INTO candidate_site (site_id, kind, geom) VALUES"
                    " (%s, %s, ST_SetSRID(ST_MakePoint(103.9, 1.35), 4326))",
                    [(s.site_id, s.kind.value) for s in S.sites])
                cur.executemany(
                    "INSERT INTO station_site (station_id, site_id, distance_m, threshold_m)"
                    " VALUES (%(station_id)s, %(site_id)s, %(distance_m)s, %(threshold_m)s)",
                    S.near + [{**S.near[0], "site_id": S.sites[-1].site_id,
                                "distance_m": 80.0, "threshold_m": 100}])
                collect._copy(cur, READINGS)
            site_ids, active, counts = I.read_counts(conn, START, END)
            ours = {i.site_id: i for i in I._measure(
                [s for s in site_ids if s.startswith("SYN-")], active, counts, START, END)}
            assert ours == _computed()
            for _ in range(2):
                I.write_indicators(conn, list(ours.values()), START, END)
            row = conn.execute("SELECT count(*) FROM site_indicators WHERE site_id LIKE 'SYN-%%'"
                               " AND window_start = %s", (START,)).fetchone()
            assert row == (len(S.sites),)
        finally:
            conn.rollback()
