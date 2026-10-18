"""Rule register (SYSTEM_DESIGN.md §4.4, #17), checked against optev.sample."""

from pathlib import Path

import pytest

from optev.contracts import Outcome, RuleSource
from optev.reasoning.rules import FACTS, REGISTER, load_register
from optev.sample import load

S = load()
SAMPLE_RULES = {r.rule_id: r for r in S.rules}

# What the collected week (HDB car park availability + LTA EVCBatch) lets conform and the
# indicators produce. Rules read nothing else until more data is collected.
COLLECTED_FACTS = {"total_lots", "existing_connectors", "supply_state", "utilisation"}

GOOD = """
[[rule]]
rule_id = "R01"
condition = "Car capacity is published for the site"
source = "gov_dataset"
source_ref = "ds-hdb-availability"
required_facts = ["total_lots"]
explanation_template = "Capacity is known: {total_lots} car lots."
on_fail = "reject"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "register.toml"
    path.write_text(text, encoding="utf-8")
    return path


# The shipped register ------------------------------------------------------------------

def test_shipped_register_loads_with_an_outcome_per_rule():
    rules, on_fail = load_register()
    assert [r.rule_id for r in rules] == ["R01", "R03", "R04"]
    assert set(on_fail) == {r.rule_id for r in rules}
    assert all(o in (Outcome.REJECT, Outcome.CONDITIONAL) for o in on_fail.values())


def test_rules_read_only_facts_the_collected_week_provides():
    rules, _ = load_register()
    for r in rules:
        assert set(r.required_facts) <= COLLECTED_FACTS, r.rule_id


def test_register_agrees_with_the_sample_rules_it_shares():
    rules, on_fail = load_register()
    for r in rules:
        want = SAMPLE_RULES[r.rule_id]
        assert (r.source, r.required_facts, on_fail[r.rule_id]) == (
            want.source, want.required_facts, S.rule_on_fail[r.rule_id]
        )


def test_r01_cites_the_feed_that_supplies_lot_counts():
    # the sample cites URA capacity, which is not among the proposal's sources
    rules, _ = load_register()
    assert {r.rule_id: r.source_ref for r in rules}["R01"] == "ds-hdb-availability"


def test_every_source_class_but_policy_is_used():
    # gov_policy waits for a rule whose fact is collected; see specs/008
    rules, _ = load_register()
    assert {r.source for r in rules} == {
        RuleSource.GOV_DATASET, RuleSource.MATH_CONSTRAINT, RuleSource.PROJECT_ASSUMPTION
    }


def test_templates_render_with_a_sample_sites_facts():
    site = S.sites[0]
    ind = next(i for i in S.indicators if i.site_id == site.site_id)
    facts = {"total_lots": site.total_lots, "existing_connectors": site.existing_connectors,
             "supply_state": ind.supply_state.value}
    rules, _ = load_register()
    for r in rules:
        text = r.explanation_template.format(**facts)
        assert "{" not in text and text.endswith(".")


def test_no_threshold_is_written_into_a_rule():
    # §2.3 rule 5: numbers come from optev.assumptions, named, never written inline
    text = REGISTER.read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    assert "%" not in body and "0.15" not in body and "0.05" not in body


# Broken registers -----------------------------------------------------------------------

def test_a_minimal_register_loads(tmp_path):
    rules, on_fail = load_register(_write(tmp_path, GOOD))
    assert [r.rule_id for r in rules] == ["R01"] and on_fail == {"R01": Outcome.REJECT}


@pytest.mark.parametrize(("old", "new", "message"), [
    ('on_fail = "reject"', 'on_fail = "defer"', "on_fail must be reject or conditional"),
    ('on_fail = "reject"', "", "on_fail must be reject or conditional"),
    ('["total_lots"]', '["total_lots", "lots"]', "unknown required_facts ['lots']"),
    ("{total_lots} car lots", "{total_lots} lots, {utilisation:.0%} used",
     "uses ['utilisation'], which are not in required_facts"),
    ('source_ref = "ds-hdb-availability"', 'source_ref = "doc-x"',
     "gov_dataset rule needs a source_ref starting ds-"),
    ('source_ref = "ds-hdb-availability"', "", "needs a source_ref"),
    ('source = "gov_dataset"', 'source = "hunch"', "invalid source"),
    ('rule_id = "R01"', "", "invalid rule_id"),
])
def test_each_fault_is_named(tmp_path, old, new, message):
    with pytest.raises(ValueError, match="rule register is invalid") as err:
        load_register(_write(tmp_path, GOOD.replace(old, new)))
    assert message in str(err.value)


def test_every_problem_is_reported_at_once(tmp_path):
    broken = GOOD.replace('on_fail = "reject"', 'on_fail = "accept"').replace(
        '["total_lots"]', '["total_lots", "lots"]')
    with pytest.raises(ValueError) as err:
        load_register(_write(tmp_path, broken))
    assert "on_fail" in str(err.value) and "unknown required_facts" in str(err.value)


def test_duplicate_ids_are_refused(tmp_path):
    with pytest.raises(ValueError, match="duplicate rule_id R01"):
        load_register(_write(tmp_path, GOOD + GOOD))


def test_empty_and_malformed_files_are_refused(tmp_path):
    with pytest.raises(ValueError, match="no \\[\\[rule\\]\\] entries"):
        load_register(_write(tmp_path, "# nothing yet\n"))
    with pytest.raises(ValueError, match="not valid TOML"):
        load_register(_write(tmp_path, "[[rule]\n"))


def test_design_fact_keys_are_the_ten_in_section_4_4():
    assert len(FACTS) == 10 and COLLECTED_FACTS <= FACTS
