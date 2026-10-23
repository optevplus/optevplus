"""Rules check (§6 Stage 4): blind sheets, Cohen's kappa, agreement with the system."""

import csv

import pytest

from optev.contracts import Decision, Outcome
from optev.evaluation import rules_check as C

DECISIONS, FACTS = C.sample_facts()


def _decisions(counts: dict[Outcome, int]) -> list[Decision]:
    out, i = [], 0
    for o, n in counts.items():
        for _ in range(n):
            out.append(Decision(site_id=f"S{i:03d}", outcome=o))
            i += 1
    return out


def test_pick_meets_the_quota_and_hides_the_outcome_in_the_order():
    pool = _decisions({o: 20 for o in Outcome})
    ids, short = C.pick(pool)
    assert len(ids) == 30 and short == {}
    outcome = {d.site_id: d.outcome for d in pool}
    assert {o: sum(outcome[i] is o for i in ids) for o in Outcome} == {
        Outcome.ACCEPT: 8, Outcome.CONDITIONAL: 8, Outcome.DEFER: 7, Outcome.REJECT: 7}
    assert ids != sorted(ids, key=lambda i: list(Outcome).index(outcome[i]))  # shuffled
    assert C.pick(pool) == C.pick(pool)  # seeded


def test_pick_reports_a_shortfall_instead_of_inventing_sites():
    ids, short = C.pick(DECISIONS)  # the sample has 3 defer and 2 reject sites
    assert short == {Outcome.DEFER: 4, Outcome.REJECT: 5} and len(ids) == 21


def test_evidence_rows_carry_no_verdict():
    rows = C.evidence(["SYN-S-13", "SYN-S-27"], FACTS)
    assert set(rows[0]) == set(C.EVIDENCE)
    assert not {"outcome", "verdict", "failing_rules", "results"} & set(rows[0])
    assert "total_lots" in rows[1]["missing"]  # hawker centre: no lot count


@pytest.mark.parametrize(("a", "b", "want"), [
    (["accept", "reject"] * 5, ["accept", "reject"] * 5, 1.0),
    (["accept", "reject"] * 5, ["reject", "accept"] * 5, -1.0),
    # the standard worked example: 50 items, 20 both yes, 15 both no, 5 yes/no, 10 no/yes;
    # p_o = 0.70, p_e = 0.5 x 0.6 + 0.5 x 0.4 = 0.50, so kappa = 0.40
    (["yes"] * 20 + ["no"] * 15 + ["yes"] * 5 + ["no"] * 10,
     ["yes"] * 20 + ["no"] * 15 + ["no"] * 5 + ["yes"] * 10, 0.40),
])
def test_kappa(a, b, want):
    assert C.kappa(a, b) == pytest.approx(want, abs=1e-3)


def test_score_compares_both_raters_with_each_other_and_the_system():
    system = {"A": {"verdict": "accept", "why": ""}, "B": {"verdict": "reject", "why": "R03"},
              "C": {"verdict": "defer", "why": "R01"}}
    ratings = {
        "gurneet": {"A": {"verdict": "accept", "reason": ""},
                    "B": {"verdict": "reject", "reason": ""},
                    "C": {"verdict": "defer", "reason": ""}},
        "shrey": {"A": {"verdict": "accept", "reason": ""},
                  "B": {"verdict": "conditional", "reason": "could add one"},
                  "C": {"verdict": "defer", "reason": ""}},
    }
    summary, per_site, disagreements = C.score(ratings, system)
    assert [r["comparison"] for r in summary] == [
        "gurneet vs shrey", "gurneet vs system", "shrey vs system"]
    assert summary[1]["agreement"] == 1.0 and summary[2]["agreement"] == pytest.approx(2 / 3)
    assert [d["site_id"] for d in disagreements] == ["B"]
    assert disagreements[0]["shrey_reason"] == "could add one" and len(per_site) == 3


def test_score_refuses_incomplete_or_invalid_sheets():
    system = {"A": {"verdict": "accept"}}
    with pytest.raises(ValueError, match="no verdict"):
        C.score({"gurneet": {"A": {"verdict": "accept"}}, "shrey": {"A": {"verdict": ""}}},
                system)
    with pytest.raises(ValueError, match="must be one of"):
        C.score({"gurneet": {"A": {"verdict": "accept"}}, "shrey": {"A": {"verdict": "ok"}}},
                system)


def test_pick_then_score_round_trip(tmp_path):
    short = C.write_sheets(DECISIONS, FACTS, tmp_path)
    assert short  # the sample is short of defer and reject sites
    key = C._read(tmp_path / "system_key.csv")
    for r in C.RATERS:  # a stand-in rater that copies the key, to exercise the files only
        path = tmp_path / f"rating_{r}.csv"
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        assert all(row["verdict"] == "" for row in rows)  # blank for the rater
        for row in rows:
            row["verdict"] = key[row["site_id"]]["verdict"]
        C._write(path, rows, list(rows[0]))
    summary = C.write_scores(tmp_path)
    assert all(r["agreement"] == 1.0 for r in summary)
    assert (tmp_path / "summary.md").read_text(encoding="utf-8").startswith("| Comparison |")
