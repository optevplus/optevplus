"""The screen shows words, never ids (optev.app.labels), on the synthetic sample."""

import re

import pytest

from optev.app import labels as L
from optev.app import shell
from optev.app.data import from_sample
from optev.contracts import Outcome, SiteKind

ID = re.compile(r"\b(SYN-S-\d+|hdb:\w+|ura:\w+|R0[1-6])\b")


@pytest.fixture(scope="module")
def data():
    return from_sample()


def test_every_code_has_words(data):
    assert set(L.RULE_NAMES) == {r.rule_id for r in data.rules}
    assert {k.value for k in SiteKind} <= set(L.KINDS)
    assert set(L.SUPPLY) == {"supply_active", "supply_idle", "no_supply", "unobserved"}
    assert L.time_bin("wd-18") == "Weekday, 18:00" and L.time_bin("all") == "Daily Average"
    assert all(o.value.title() for o in Outcome)


def test_a_site_is_a_place_never_an_id(data):
    named = next(s for s in data.sites if s.site_id in data.site_names)
    unnamed = next(s for s in data.sites if s.site_id not in data.site_names)
    assert L.site(data, named.site_id).startswith(data.site_names[named.site_id])
    assert not ID.search(L.site(data, unnamed.site_id))
    assert L.area(data, "TM") == "Tampines"


def test_tables_have_no_ids_and_no_snake_case_headers(data):
    plan, _ = shell.plan(data, shell.Request("base", None, 12, None))
    rows = L.table(shell.ranking(shell.site_rows(data, plan)), data)
    for row in rows:
        assert not any("_" in key for key in row)
        assert not any(isinstance(v, str) and ID.search(v) for v in row.values())
    assert list(rows[0])[:2] == ["Rank", "Site"]


def test_people_can_ask_by_name_and_id_questions_still_work(data):
    sid = next(iter(data.site_names))
    name = data.site_names[sid]
    assert L.resolve_names(f"Why was {name} chosen?", data) == f"Why was {sid} chosen?"
    assert L.resolve_names("Why was SYN-S-13 rejected?", data) == "Why was SYN-S-13 rejected?"


def test_an_answer_reads_without_ids(data):
    text, sources = L.readable_answer(
        "SYN-S-04 passed R03 [SYN-S-04] [doc-lta-ev-factsheet-2021] "
        "[base:all:points=12:budget=-].", data)
    assert not ID.search(text) and "[" not in text
    assert "Room for Another Point" in text
    assert any("factsheet" in s for s in sources) and not any(ID.search(s) for s in sources)
    assert "12-point plan island-wide" in " ".join(sources)


def test_area_codes_read_as_names_and_are_not_shown_twice(data):
    assert L.words(data, "TM") == "Tampines"
    _, sources = L.readable_answer("Tampines is busiest [TM] [PR].", data)
    assert sources == ["Tampines", "Pasir Ris"]
    rows = L.table([{"planning_area": "TM", "name": "TAMPINES", "sites_with_chargers": 3}], data)
    assert rows == [{"Planning Area": "Tampines", "Sites with Chargers": 3}]


def test_shared_addresses_get_distinct_labels_and_both_sites_resolve():
    from optev.app.data import AppData, unique_names
    from optev.contracts import CandidateSite, Coordinate, SiteKind

    def site(sid, lots):
        return CandidateSite(site_id=sid, kind=SiteKind.HDB_CAR_PARK, total_lots=lots,
                             coord=Coordinate(lat=1.3, lon=103.8))

    sites = [site("hdb:JS3L", 2010), site("hdb:JM12", 468), site("hdb:A76", 632)]
    names = unique_names({"hdb:JS3L": "Blk 624A Jurong West Street 61",
                          "hdb:JM12": "Blk 624A Jurong West Street 61",
                          "hdb:A76": "Blk 613A Ang Mo Kio Avenue 4"}, sites)
    assert names["hdb:JS3L"] == "Blk 624A Jurong West Street 61 (2,010 lots)"
    assert names["hdb:JM12"] == "Blk 624A Jurong West Street 61 (468 lots)"
    data = AppData("sample", [], sites, [], [], [], [], [], {}, [], site_names=names)
    q = "Compare Blk 613A Ang Mo Kio Avenue 4 and Blk 624A Jurong West Street 61."
    assert L.resolve_names(q, data) == "Compare hdb:A76 and hdb:JS3L."
    assert L.resolve_names("Why was Blk 624A Jurong West Street 61 (468 lots) rejected?",
                           data) == "Why was hdb:JM12 rejected?"


def test_answer_numbers_read_as_a_person_would_write_them(data):
    t = L.tidy_numbers
    assert t("at a cost of 46250.0, while") == "at a cost of S$46,250, while"
    assert t("a cost of S$27750.0") == "a cost of S$27,750"
    assert t("costing 111000") == "costing S$111,000"
    assert t("a budget of 150000.00") == "a budget of S$150,000"
    assert t("has 2010 parking lots") == "has 2,010 parking lots"  # a count, not a year
    assert t("by 2030 the fleet grows") == "by 2030 the fleet grows"  # a year stays
    assert t("3.222 arrivals and a share of 0.682") == "3.222 arrivals and a share of 0.682"
    assert t("5.0 points") == "5 points"


def test_block_numbers_in_names_are_not_reformatted(data):
    from optev.app.data import AppData
    from optev.contracts import CandidateSite, Coordinate, SiteKind

    s = CandidateSite(site_id="hdb:X1", kind=SiteKind.HDB_CAR_PARK, total_lots=500,
                      coord=Coordinate(lat=1.3, lon=103.8))
    d = AppData("sample", [], [s], [], [], [], [], [], {}, [],
                site_names={"hdb:X1": "Blk 1001 Jurong West Street 41"})
    text, _ = L.readable_answer("hdb:X1 costs 9250.0 per point [hdb:X1].", d)
    assert text == "Blk 1001 Jurong West Street 41 costs S$9,250 per point."


def test_a_source_cited_without_its_prefix_still_shows_as_a_place(data):
    sid = next(s.site_id for s in data.sites if s.site_id in data.site_names)
    short = sid.rsplit(":", 1)[-1] if ":" in sid else sid
    _, sources = L.readable_answer(f"It is busy [{short}].", data)
    assert sources == [data.site_names[sid]]
