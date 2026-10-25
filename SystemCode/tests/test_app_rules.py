"""Rules page (#31): decisions, rule results with their sources, waivers, on optev.sample."""

from pathlib import Path

from optev.app import data as D
from optev.app import rules_view as V
from optev.contracts import Outcome

DATA = D.from_sample()
DECISION = {d.site_id: d for d in DATA.decisions}


def test_register_rows_name_each_rules_source_and_link():
    rows = V.register_rows(DATA)
    assert [r["rule"] for r in rows] == [r.rule_id for r in DATA.rules]
    for row, rule in zip(rows, DATA.rules, strict=True):
        assert row["source type"] == V.SOURCE_CLASS[rule.source.value]
        assert row["source"] != rule.source_ref  # resolved to a title or a name
        if rule.source_ref.startswith(("ds-", "doc-")):  # an assumption has no web page
            assert row["link"] and row["link"].startswith("https://")
        assert row["if it fails"] in ("reject", "conditional")


def test_decision_table_filters_by_outcome_and_area():
    every = V.decision_table(DATA)
    assert len(every) == 30
    # car parks first, then reject, conditional, defer, accept, then place name
    car_park = [r["kind"].endswith("car_park") for r in every]
    assert car_park == sorted(car_park, reverse=True)
    for group in (True, False):
        rows = [r for r, cp in zip(every, car_park, strict=True) if cp is group]
        ranks = [[o.value for o in V.OUTCOME_ORDER].index(r["outcome"]) for r in rows]
        assert ranks == sorted(ranks)
        for o in V.OUTCOME_ORDER:
            names = [(DATA.site_names.get(r["site_id"]) or r["site_id"]).lower()
                     for r in rows if r["outcome"] == o.value]
            assert names == sorted(names)
    assert every[0]["outcome"] == "reject" and every[0]["kind"].endswith("car_park")
    rejected = V.decision_table(DATA, "reject")
    assert {r["site_id"] for r in rejected} == {"SYN-S-13", "SYN-S-14"}
    assert all(r["planning_area"] == "PR" for r in V.decision_table(DATA, None, "PR"))


def test_rule_results_show_every_rule_with_its_verdict_and_source():
    rows = V.rule_results(DATA, DECISION["SYN-S-13"])
    assert [r["rule"] for r in rows] == [r.rule_id for r in DATA.rules]
    room = next(r for r in rows if r["rule"] == "R03")
    assert (room["result"], room["detail"]) == ("failed", "room 0")
    assert room["source type"] == "Arithmetic limit"


def test_missing_data_reads_as_unevaluated_not_failed():
    rows = V.rule_results(DATA, DECISION["SYN-S-27"])  # hawker centre: no lot count
    r01 = next(r for r in rows if r["rule"] == "R01")
    assert (r01["result"], r01["detail"]) == ("unevaluated (missing data)", "total_lots missing")


def test_waivers_use_the_engines_outcome_policy():
    assert V.waivers(DATA, DECISION["SYN-S-13"]) == {"R03": Outcome.ACCEPT}
    assert V.waivers(DATA, DECISION["SYN-S-14"]) == {"R04": Outcome.ACCEPT}
    assert V.waivers(DATA, DECISION["SYN-S-01"]) == {}  # nothing failed


def test_rules_page_renders_on_the_sample(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(D, "ENV_FILE", tmp_path / ".env")
    page = Path(D.__file__).with_name("views") / "2_Rules.py"
    at = AppTest.from_file(str(page), default_timeout=60).run()
    assert not at.exception
    assert [m.label for m in at.metric] == ["Accept", "Conditional", "Defer", "Reject"]
    assert len(at.dataframe) >= 3  # register, decisions, one site's results
