"""Ranked sites as a list on the Site Map (optev.app.ranking_view), on optev.sample."""

from pathlib import Path

from optev.app import data as D
from optev.app import ranking_view as RV
from optev.app import shell as S

DATA = D.from_sample()
RANKED = S.ranking(S.site_rows(DATA, DATA.allocations[0]))
CARDS = [RV.card(r, DATA) for r in RANKED]
MAP = Path(D.__file__).with_name("views") / "1_Map.py"


def _items(html: str) -> tuple[int, int]:
    """(top picks, other rows) in a page's HTML."""
    return html.count('class="ox-rl-item ox-rl-top"'), html.count('class="ox-rl-item"')


def test_rows_follow_the_ranking_and_only_the_best_is_the_top_pick():
    assert [c["rank"] for c in CARDS] == [r["rank"] for r in RANKED]
    html = RV.rows(CARDS[:RV.TOP], top=True, head=True) + RV.rows(CARDS[RV.TOP:])
    assert _items(html) == (1, len(CARDS) - 1)
    assert html.count("Top pick") == 1 and ">01<" in html
    assert CARDS[0]["new"] == max(c["new"] for c in CARDS)  # the most recommended points first


def test_one_line_per_site_with_words_not_ids():
    assert all(not c["place"].startswith("SYN-") for c in CARDS)
    assert {c["outcome"] for c in CARDS} <= {"Accept", "Conditional", "Defer", "Reject",
                                              "Unscreened"}
    item = RV.row(CARDS[1])
    assert item.count('class="ox-rl-row"') == 1  # every figure on the one row


def test_a_missing_figure_is_a_dash_never_zero():
    row = {**RANKED[-1], "utilisation (observed)": None, "demand_per_h (inferred)": None,
           "existing_points (observed)": None}
    c = RV.card(row, DATA)
    assert (c["utilisation"], c["demand"], c["existing"]) == ("—", "—", "—")
    assert RV.card({**row, "utilisation (observed)": 0.0}, DATA)["utilisation"] == "0%"


def test_a_lower_bound_reads_as_at_least():
    row = {**RANKED[0], "demand_per_h (inferred)": 1.5, "lower_bound": True}
    assert RV.card(row, DATA)["demand"] == "≥ 1.50"


def test_every_figure_keeps_its_layer_in_the_header_and_its_tooltip():
    head, item = RV.header(), RV.row(CARDS[0])
    for _, label, layer in RV.FIGURES:
        assert f"<em>{layer}</em>" in head
        assert f'title="{label} ({layer})"' in item


def test_the_reason_line_and_escaping():
    failed = next(c for c in CARDS if c["why"])
    label = "To confirm:" if failed["outcome"] == "Conditional" else "Why:"
    assert f'<div class="ox-rl-why">{label}' in RV.row(failed)
    assert "ox-rl-why" not in RV.row({**CARDS[0], "why": ""})
    html = RV.row({**CARDS[0], "place": "<script>x</script>", "why": "a & b"})
    assert "<script>" not in html and "&lt;script&gt;" in html and "a &amp; b" in html


def test_the_site_map_lists_every_site_and_keeps_the_table(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(D, "ENV_FILE", tmp_path / ".env")
    at = AppTest.from_file(str(MAP), default_timeout=60).run()
    assert not at.exception
    assert _items("".join(m.value for m in at.markdown)) == (1, len(CARDS) - 1)
    assert at.dataframe  # the full table, in the "View as a Table" expander


def test_show_more_adds_a_page_of_rows(monkeypatch, tmp_path):
    # The real data has thousands of sites, so rows come a page at a time.
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(D, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(RV, "PAGE", 10)
    at = AppTest.from_file(str(MAP), default_timeout=60).run()

    def others() -> int:
        return _items("".join(m.value for m in at.markdown))[1]

    assert others() == 10
    next(b for b in at.button if b.label == "Show More Sites").click().run()
    assert not at.exception and others() == 20
