"""Ranked sites as tiles on the Site Map (optev.app.ranking_view), on optev.sample."""

from pathlib import Path

from optev.app import data as D
from optev.app import ranking_view as RV
from optev.app import shell as S

DATA = D.from_sample()
RANKED = S.ranking(S.site_rows(DATA, DATA.allocations[0]))
CARDS = [RV.card(r, DATA) for r in RANKED]


def test_tiles_follow_the_ranking_and_the_podium_is_the_top_three():
    assert [c["rank"] for c in CARDS] == [r["rank"] for r in RANKED]
    top = RV.grid(CARDS[:RV.TOP], top=True)
    assert top.count('class="ox-rk ox-rk-top"') == RV.TOP
    assert all(f"#{c['rank']}<" in top for c in CARDS[:RV.TOP])
    assert CARDS[0]["new"] == max(c["new"] for c in CARDS)  # the most recommended points first


def test_tiles_show_words_not_ids():
    assert all(not c["place"].startswith("SYN-") for c in CARDS)
    assert {c["outcome"] for c in CARDS} <= {"Accept", "Conditional", "Defer", "Reject",
                                              "Unscreened"}


def test_a_missing_figure_is_a_dash_never_zero():
    row = {**RANKED[-1], "utilisation (observed)": None, "demand_per_h (inferred)": None}
    c = RV.card(row, DATA)
    assert c["utilisation"] == "—" and c["demand"] == "—"
    assert RV.card({**row, "utilisation (observed)": 0.0}, DATA)["utilisation"] == "0%"


def test_a_lower_bound_reads_as_at_least():
    row = {**RANKED[0], "demand_per_h (inferred)": 1.5, "lower_bound": True}
    assert RV.card(row, DATA)["demand"] == "≥ 1.50"


def test_every_figure_keeps_its_layer():
    html = RV.tile(CARDS[0])
    for label in ("(recommended)", "(inferred)", "(observed)"):
        assert label in html


def test_failed_rules_are_explained_and_text_is_escaped():
    failed = next(c for c in CARDS if c["why"])
    assert ("Why:" if failed["outcome"] != "Conditional" else "To confirm:") in RV.tile(failed)
    nasty = {**CARDS[0], "place": "<script>x</script>", "why": "a & b"}
    html = RV.tile(nasty)
    assert "<script>" not in html and "&lt;script&gt;" in html and "a &amp; b" in html


def test_the_site_map_shows_tiles_and_keeps_the_table(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(D, "ENV_FILE", tmp_path / ".env")
    page = Path(D.__file__).with_name("pages") / "1_Map.py"
    at = AppTest.from_file(str(page), default_timeout=60).run()
    assert not at.exception
    tiles = "".join(m.value for m in at.markdown)
    assert tiles.count('class="ox-rk ox-rk-top"') == RV.TOP
    assert tiles.count('class="ox-rk"') == len(CARDS) - RV.TOP  # 27 more: one page
    assert at.dataframe  # the full table, in the "View as a Table" expander


def test_show_more_adds_a_page_of_tiles(monkeypatch, tmp_path):
    # The real data has thousands of sites, so tiles come a page at a time.
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(D, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(RV, "PAGE", 10)
    page = Path(D.__file__).with_name("pages") / "1_Map.py"
    at = AppTest.from_file(str(page), default_timeout=60).run()

    def compact() -> int:
        return "".join(m.value for m in at.markdown).count('class="ox-rk"')

    assert compact() == 10
    next(b for b in at.button if b.label == "Show More Sites").click().run()
    assert not at.exception and compact() == 20
