"""App shell (#30): data loading and the Map page, on optev.sample."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from optev.app import data as D
from optev.app import shell as S
from optev.contracts import Outcome, SiteIndicators

DATA = D.from_sample()
BASE = S.Request("base", None, 12, None)  # the sample's stored reference plan


# Data -------------------------------------------------------------------------------------

def test_sample_bundle_has_everything_the_pages_need():
    assert DATA.source == "sample"
    assert len(DATA.sites) == len(DATA.decisions) == 30
    assert {d.site_id for d in DATA.decisions} == {s.site_id for s in DATA.sites}
    assert all(e.time_bin == "all" for e in DATA.estimates)
    assert DATA.rules and set(DATA.on_fail) == {r.rule_id for r in DATA.rules}
    assert "ds-hdb-availability" in DATA.references and DATA.allocations


def test_sample_decisions_come_from_the_current_register():
    assert {r.rule_id for d in DATA.decisions for r in d.results} == {
        r.rule_id for r in DATA.rules}


def test_load_uses_the_sample_without_a_database(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(D, "ENV_FILE", tmp_path / ".env")
    assert D.load().source == "sample"


def test_models_nest_coordinates_convert_times_and_skip_bad_rows():
    row = {"site_id": "SYN-S-01", "window_start": datetime(2026, 10, 7, tzinfo=UTC),
           "window_end": datetime(2026, 10, 14, tzinfo=UTC), "supply_state": "supply_active",
           "active_connectors": 4, "utilisation": 0.5, "saturated_fraction": 0.1,
           "dwell_opportunity": None, "observation_coverage": 1.0}
    bad = row | {"utilisation": 2.0}
    [ind] = D._models(SiteIndicators, [row, bad])
    assert ind.window_end == "2026-10-14T00:00:00+00:00"
    [site] = D._models(type(DATA.sites[0]), [
        DATA.sites[0].model_dump(mode="json", exclude={"coord"})
        | {"lat": 1.35, "lon": 103.95}])
    assert (site.coord.lat, site.coord.lon) == (1.35, 103.95)


class FakeCursor:
    """Answers each query in D.SQL from the sample, as Postgres rows."""

    def __init__(self) -> None:
        s = DATA

        def flat(m):  # a table row: coordinates split into lat / lon
            row = {k: v for k, v in m.model_dump(mode="json").items() if k != "coord"}
            return row | ({"lat": m.coord.lat, "lon": m.coord.lon} if hasattr(m, "coord") else {})

        self.rows = {
            D.SQL["areas"]: [a.model_dump(mode="json") for a in s.planning_areas],
            D.SQL["sites"]: [flat(x) for x in s.sites],
            D.SQL["car_parks"]: [flat(x) for x in s.car_parks],
            D.SQL["indicators"]: [x.model_dump(mode="json") for x in s.indicators],
            D.SQL["estimates"]: [x.model_dump(mode="json") for x in s.estimates],
            D.SQL["decisions"]: [{"site_id": d.site_id, "outcome": d.outcome.value}
                                 for d in s.decisions],
            D.SQL["results"]: [{"site_id": d.site_id, **r.model_dump()}
                               for d in s.decisions for r in d.results],
            D.SQL["scenarios"]: [x.model_dump(mode="json", exclude={"planned"})
                                 for x in s.scenarios],
            D.SQL["planned"]: [{"scenario_id": "base", "site_id": "SYN-S-07", "connectors": 2,
                                "selected_by": "test"}],
            D.SQL["allocations"]: [{"allocation_id": "base:all:points=12:budget=-",
                                    **s.allocations[0].model_dump(mode="json",
                                                                  exclude={"items"})}],
            D.SQL["items"]: [{"allocation_id": "base:all:points=12:budget=-",
                              **i.model_dump(mode="json")} for i in s.allocations[0].items],
            D.SQL["profiles"]: [x.model_dump(mode="json") for x in s.profiles],
            D.SQL["patterns"]: [{"site_id": k, "cluster": c, "label": s.pattern_labels[c]}
                                for k, c in s.patterns.items()],
        }

    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def cursor(self): return self
    def execute(self, sql, params=None): return iter([dict(r) for r in self.rows[sql]])


def test_postgres_bundle_reads_every_table(monkeypatch):
    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda url, row_factory=None: FakeCursor())
    pg = D.from_postgres("postgresql://fake")
    assert pg.source == "postgres" and len(pg.sites) == 30
    assert [d.outcome for d in pg.decisions] == [d.outcome for d in DATA.decisions]
    assert pg.decisions[0].results == DATA.decisions[0].results
    base = next(s for s in pg.scenarios if s.scenario_id == "base")
    assert [(p.site_id, p.connectors) for p in base.planned] == [("SYN-S-07", 2)]
    assert pg.allocations[0].total_connectors == DATA.allocations[0].total_connectors
    assert pg.profiles == DATA.profiles
    assert (pg.patterns, pg.pattern_labels) == (DATA.patterns, DATA.pattern_labels)


# Map page logic ---------------------------------------------------------------------------

def test_plan_falls_back_to_the_stored_plan_without_the_allocator(monkeypatch):
    import builtins

    real = builtins.__import__

    def no_allocator(name, *args, **kwargs):
        if name == "optev.reasoning.allocate":
            raise ImportError(name)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_allocator)
    plan, origin = S.plan(DATA, BASE)
    assert plan == DATA.allocations[0] and origin.startswith("stored plan")
    none, why = S.plan(DATA, S.Request("base", "TM", 99, None))
    assert none is None and "allocator" in why
    assert S.plan(DATA, S.Request("base"))[0] is None  # neither points nor budget


def test_site_rows_label_every_figure_with_its_layer():
    rows = S.site_rows(DATA, DATA.allocations[0])
    assert len(rows) == 30
    labelled = [k for k in rows[0] if "(" in k]
    assert {k.split("(")[1].rstrip(")") for k in labelled} == {
        "observed", "inferred", "recommended"}
    assert sum(r["new_points (recommended)"] for r in rows) == 12
    no_supply = next(r for r in rows if r["site_id"] == "SYN-S-27")
    assert no_supply["utilisation (observed)"] is None  # invariant 2: never 0
    assert {r["planning_area"] for r in S.site_rows(DATA, None, "PR")} == {"PR"}


def test_ranking_puts_eligible_and_recommended_sites_first():
    ranked = S.ranking(S.site_rows(DATA, DATA.allocations[0]))
    assert [r["rank"] for r in ranked] == list(range(1, 31))
    eligible = [r["outcome"] in S.ELIGIBLE for r in ranked]
    assert eligible == sorted(eligible, reverse=True)
    top = ranked[0]
    assert top["new_points (recommended)"] == max(r["new_points (recommended)"] for r in ranked)


def test_demand_hexes_sum_inferred_demand_per_cell():
    rows = S.site_rows(DATA, None)
    hexes = S.demand_hexes(rows)
    total = sum(r["demand_per_h (inferred)"] or 0 for r in rows)
    assert sum(h["demand_per_h"] for h in hexes) == pytest.approx(total, abs=0.05)
    assert sum(h["sites"] for h in hexes) == sum(r["demand_per_h (inferred)"] is not None
                                                 for r in rows)


def test_funnel_counts_every_outcome():
    counts = S.funnel(DATA)
    assert set(counts) == {o.value for o in Outcome} and sum(counts.values()) == 30
    assert S.funnel(DATA, {"SYN-S-13"}) == {"accept": 0, "reject": 1, "defer": 0,
                                           "conditional": 0}


# The page itself ----------------------------------------------------------------------------

def test_map_page_renders_on_the_sample(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(D, "ENV_FILE", tmp_path / ".env")
    page = Path(D.__file__).with_name("main.py")
    at = AppTest.from_file(str(page), default_timeout=60).run()
    assert not at.exception
    assert any("synthetic sample" in i.value for i in at.info)
    assert [m.label for m in at.metric][:2] == ["Candidate sites", "Accept"]
    assert at.dataframe  # the ranking
