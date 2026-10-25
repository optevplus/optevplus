"""Stage 4 rules check (optev.evaluation.rules_check) on the synthetic sample."""

import pytest

from optev.contracts import Outcome
from optev.evaluation.rules_check import (
    FACT_COLUMNS,
    RATERS,
    kappa,
    markdown,
    pick,
    reason_coded,
    score,
    screened,
    sheet_rows,
)
from optev.reasoning.rules import load_register
from optev.sample import load


@pytest.fixture(scope="module")
def found():
    s = load()
    rules, on_fail = load_register()
    return screened(s.sites, s.car_parks, s.indicators, {}, rules, on_fail)


def test_pick_is_stratified_capped_and_repeatable(found):
    ids = pick(found.decisions, seed=3)
    assert ids == pick(found.decisions, seed=3)
    assert len(ids) == len(set(ids))
    have = {o: sum(d.outcome is o for d in found.decisions.values()) for o in Outcome}
    got = {o: sum(found.decisions[i].outcome is o for i in ids) for o in Outcome}
    quota = {Outcome.ACCEPT: 8, Outcome.CONDITIONAL: 8, Outcome.DEFER: 7, Outcome.REJECT: 7}
    assert got == {o: min(quota[o], have[o]) for o in Outcome}


def test_the_sheet_is_blind_and_leaves_missing_facts_blank(found):
    rows = sheet_rows(pick(found.decisions), found.facts)
    assert set(rows[0]) == {"site_id", *FACT_COLUMNS, *RATERS}  # no verdict column
    assert all(r[k] == "" for r in rows for k in RATERS)
    assert all(r["utilisation"] != 0 or found.facts[r["site_id"]].get("utilisation") == 0
               for r in rows)


def test_kappa_matches_textbook_values():
    assert kappa(list("aabb"), list("aabb")) == 1.0
    assert kappa(list("abab"), list("baba")) == -1.0
    # 20 items: 15 agree; marginals a 10/10, b 10/10 -> p_e 0.5, κ 0.5
    a = ["y"] * 10 + ["n"] * 10
    b = ["y"] * 8 + ["n"] * 2 + ["y"] * 2 + ["n"] * 8
    assert kappa(a, b) == pytest.approx((0.8 - 0.5) / 0.5)
    assert kappa(["x", "x"], ["x", "x"]) is None
    with pytest.raises(ValueError):
        kappa(["x"], [])


def test_raters_who_copy_the_system_score_perfectly(found):
    rows = [{**r, "rater_a": found.decisions[r["site_id"]].outcome.value,
             "rater_b": found.decisions[r["site_id"]].outcome.value.upper()}
            for r in sheet_rows(pick(found.decisions), found.facts)]
    result = score(rows, found.decisions)
    assert result["kappa_raters"] == 1.0
    assert result["agreement_a"] == result["agreement_b"] == 1.0
    assert result["agreement_consensus"] == 1.0
    assert result["reason_codes"] == 1.0
    assert result["disagreements"] == []
    assert "κ between raters | 1.00" in markdown(result)


def test_a_disagreement_is_listed_and_lowers_agreement(found):
    rows = [{**r, "rater_a": found.decisions[r["site_id"]].outcome.value,
             "rater_b": found.decisions[r["site_id"]].outcome.value}
            for r in sheet_rows(pick(found.decisions), found.facts)]
    first = rows[0]["site_id"]
    wrong = next(o.value for o in Outcome if o is not found.decisions[first].outcome)
    rows[0]["rater_b"] = wrong
    result = score(rows, found.decisions)
    assert result["agreement_b"] == pytest.approx(1 - 1 / len(rows))
    assert result["disagreements"][0]["site_id"] == first
    assert "| " + first in markdown(result)


def test_a_half_rated_sheet_is_refused(found):
    rows = sheet_rows(pick(found.decisions), found.facts)
    with pytest.raises(ValueError):
        score(rows, found.decisions)


def test_every_non_accept_verdict_has_a_reason_code(found):
    assert all(reason_coded(d) for d in found.decisions.values())
