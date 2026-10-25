"""App shell (#30): data loading and the Map page, on optev.sample."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from optev.app import data as D
from optev.app import shell as S
from optev.app.auth import SESSION_KEY
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
            D.SQL["car_park_names"]: [{"site_id": k, "name": v.upper()}
                                      for k, v in s.site_names.items()],
            D.SQL["has_amenities"]: [{"ok": False}],
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
    page = Path(D.__file__).with_name("views") / "1_Map.py"
    at = AppTest.from_file(str(page), default_timeout=60).run()
    assert not at.exception
    assert any("demo dataset" in i.value for i in at.info)
    assert [m.label for m in at.metric][:2] == ["Candidate Sites", "Accept"]
    assert at.dataframe  # the ranking


def test_the_plan_follows_the_chosen_scenario():
    # Higher growth means more drivers turned away, so the same points rescue more of them;
    # before this, every scenario got today's demand and the selector changed nothing.
    from optev.app.shell import Request, plan

    data = D.from_sample()
    rescued = {}
    for sid in ("low", "base", "high"):
        result, _ = plan(data, Request(sid, None, 12, None))
        assert result is not None and hasattr(result, "items")
        rescued[sid] = sum(i.marginal_relief or 0 for i in result.items)
    assert rescued["low"] < rescued["base"] < rescued["high"]


def test_the_map_page_shows_only_a_checked_plan():
    # §4.4: only checked allocations are written or shown; the checker re-tests every
    # constraint independently of the allocator.
    from optev.app.shell import Request, plan

    result, _ = plan(D.from_sample(), Request("base", None, 12, None))
    assert result is not None and getattr(result, "checked", False)
    assert result.violations == []


def test_the_app_plans_on_every_time_bin_like_the_pipeline(monkeypatch):
    # Erlang B per time bin (§4.2): planning on the daily mean alone picked a different plan
    # on the real data than the pipeline did for the same request.
    import optev.reasoning.allocate as A
    from optev.app.shell import Request, plan

    seen = {}
    real = A.allocate

    def spy(decisions, sites, demand, scenario, **kw):
        seen["bins"] = {e.time_bin for e in demand}
        return real(decisions, sites, demand, scenario, **kw)

    monkeypatch.setattr(A, "allocate", spy)
    plan(D.from_sample(), Request("base", None, 12, None))
    assert "all" in seen["bins"] and any(b.startswith(("wd-", "we-")) for b in seen["bins"])


def test_the_app_opens_on_the_overview_with_the_top_menu(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(D, "ENV_FILE", tmp_path / ".env")
    at = AppTest.from_file(str(Path(D.__file__).with_name("main.py")), default_timeout=60)
    at.session_state[SESSION_KEY] = True  # signed in (optev.app.auth)
    at.run()
    assert not at.exception
    assert [m.label for m in at.metric] == ["Sites Screened", "Eligible Sites",
                                            "Charging Points Tracked", "Planning Areas"]
    assert at.metric[0].value == "30"  # the sample's sites


def test_the_request_carries_from_one_page_to_the_next(monkeypatch, tmp_path):
    # A planner who picks an area on the Site Map finds it still picked on Allocation.
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(D, "ENV_FILE", tmp_path / ".env")
    at = AppTest.from_file(str(Path(D.__file__).with_name("main.py")), default_timeout=90)
    at.session_state[SESSION_KEY] = True
    at.run()
    at.switch_page("views/1_Map.py").run()
    at.sidebar.selectbox(key="req_area").set_value("TM").run()
    at.sidebar.number_input(key="req_points").set_value(5).run()
    at.switch_page("views/3_Allocation.py").run()
    assert not at.exception
    assert at.sidebar.selectbox(key="req_area").value == "TM"
    assert at.sidebar.number_input(key="req_points").value == 5


def test_island_wide_stays_chosen_across_pages(monkeypatch, tmp_path):
    # Island-wide is a real option: kept as None it read as "nothing chosen" on the next page.
    from streamlit.testing.v1 import AppTest

    from optev.app.ui import ISLAND_WIDE

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(D, "ENV_FILE", tmp_path / ".env")
    at = AppTest.from_file(str(Path(D.__file__).with_name("main.py")), default_timeout=90)
    at.session_state[SESSION_KEY] = True
    at.run()
    at.switch_page("views/1_Map.py").run()
    assert at.sidebar.selectbox(key="req_area").value == ISLAND_WIDE
    at.switch_page("views/3_Allocation.py").run()
    assert not at.exception
    assert at.sidebar.selectbox(key="req_area").value == ISLAND_WIDE


def test_postgres_names_read_as_words_not_capitals(monkeypatch):
    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda url, row_factory=None: FakeCursor())
    pg = D.from_postgres("postgresql://fake")
    assert pg.site_names and all(not n.isupper() for n in pg.site_names.values())


def test_a_read_only_deployment_offers_no_way_to_write(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(D, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setenv("OPTEV_READ_ONLY", "1")
    page = Path(D.__file__).with_name("views") / "1_Map.py"
    at = AppTest.from_file(str(page), default_timeout=60).run()
    assert not at.exception
    assert any("read-only" in i.value for i in at.info)
    assert not [b for b in at.button if b.label in ("Select Site", "Clear Selection")]


def test_an_unreachable_database_shows_a_message_not_a_traceback(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    import optev.app.ui as ui

    def down(url):
        raise OSError("connection refused")

    monkeypatch.setenv("DATABASE_URL", "postgresql://unreachable.example/optev")
    monkeypatch.setattr(D, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(ui, "from_postgres", down)
    ui.clear_data()
    page = Path(D.__file__).with_name("views") / "2_Rules.py"
    at = AppTest.from_file(str(page), default_timeout=60).run()
    assert not at.exception
    assert any("data is unavailable" in e.value for e in at.error)
    ui.clear_data()
