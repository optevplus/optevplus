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
