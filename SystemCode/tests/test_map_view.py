"""The Site Map's map views (optev.app.map_view), on optev.sample."""

from pathlib import Path

from optev.app import data as D
from optev.app import map_view as MV
from optev.app import shell as S

DATA = D.from_sample()
PLAN = DATA.allocations[0]
ROWS = S.site_rows(DATA, PLAN)
HEXES = S.demand_hexes(ROWS)
COUNTS = S.funnel(DATA)


def _types(view: str) -> list[str]:
    return [layer.type for layer in MV.layers(view, ROWS, HEXES)[0]]


def test_the_plan_view_shows_numbered_badges_for_the_recommended_sites():
    picks = MV.recommended(ROWS)
    assert {r["site_id"] for r in picks} == {i.site_id for i in PLAN.items}
    assert all(r["label"] == f"+{r['new_points (recommended)']}" for r in picks)
    assert sum(r["new_points (recommended)"] for r in picks) == PLAN.total_connectors
    assert _types(MV.PLAN) == ["ScatterplotLayer", "ScatterplotLayer", "TextLayer"]


def test_eligibility_dots_are_one_size_and_coloured_by_outcome():
    layer = MV.layers(MV.ELIGIBILITY, ROWS, HEXES)[0][0]
    assert layer.type == "ScatterplotLayer"
    assert layer.radius_min_pixels == layer.radius_max_pixels  # size means nothing here
    fills = {tuple(r["fill"]) for r in layer.data}
    assert fills <= {tuple(c) for c in S.OUTCOME_COLOURS.values()}


def test_the_demand_view_is_hexagons_on_a_light_to_dark_scale():
    assert _types(MV.DEMAND) == ["H3HexagonLayer"]
    assert MV.shade(0, 10)[:3] == list(MV.LOW) and MV.shade(10, 10)[:3] == list(MV.HIGH)
    assert MV.shade(5, 0)[:3] == list(MV.LOW)  # no demand anywhere: no division by zero


def test_every_view_has_a_legend_that_says_what_the_marks_mean():
    plan = MV.legend(MV.PLAN, ROWS, HEXES, COUNTS)
    assert f"<b>{len(PLAN.items)}</b> sites get <b>{PLAN.total_connectors}</b> new points" in plan
    elig = MV.legend(MV.ELIGIBILITY, ROWS, HEXES, COUNTS)
    for outcome in MV.OUTCOMES:
        assert f"{outcome.title()} <b>{COUNTS[outcome]:,}</b>" in elig
    assert "arrivals / h" in MV.legend(MV.DEMAND, ROWS, HEXES, COUNTS)


def test_the_map_fits_the_sites_shown():
    view = MV.view_state(ROWS)
    lats = [r["lat"] for r in ROWS]
    assert min(lats) <= view.latitude <= max(lats) and view.zoom <= 15
    assert MV.view_state([]).zoom == 10.8  # nothing to show: the whole island


def test_each_view_renders_on_the_site_map(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(D, "ENV_FILE", tmp_path / ".env")
    page = Path(D.__file__).with_name("views") / "1_Map.py"
    at = AppTest.from_file(str(page), default_timeout=60).run()
    assert not at.exception
    for view in MV.VIEWS:
        at.session_state["map_view"] = view
        at.run()
        assert not at.exception, view
        legend = "".join(m.value for m in at.markdown if "ox-legend" in m.value)
        assert legend, view
