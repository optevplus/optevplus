"""Rule register (SYSTEM_DESIGN.md §4.4, #17).

The register is data, not code: `register.toml` holds one entry per rule with every `Rule`
field plus `on_fail`. `load_register` refuses a broken register with one error that lists
every problem, so a bad edit never reaches the engine.
"""

import tomllib
from pathlib import Path
from string import Formatter
from typing import Any

from pydantic import ValidationError

from optev.contracts import Outcome, Rule, RuleSource

REGISTER = Path(__file__).parent / "register.toml"

# §4.4: the only keys a rule may read. A missing value is absent, never 0.
FACTS = frozenset({
    "kind", "planning_area", "total_lots", "existing_connectors", "car_park_type",
    "supply_state", "utilisation", "land_use", "amenities_nearby", "nearest_point_m",
})
ON_FAIL = frozenset({Outcome.REJECT, Outcome.CONDITIONAL})
# What each source class may cite: ds- dataset, doc- document, asm- assumption
SOURCE_REF_PREFIXES: dict[RuleSource, tuple[str, ...]] = {
    RuleSource.GOV_DATASET: ("ds-",),
    RuleSource.GOV_POLICY: ("doc-",),
    RuleSource.MATH_CONSTRAINT: ("doc-", "ds-", "asm-"),
    RuleSource.PROJECT_ASSUMPTION: ("asm-",),
}


def _placeholders(template: str) -> set[str]:
    """Field names in a str.format template, e.g. {utilisation:.0%} -> utilisation."""
    return {
        name.split(".")[0].split("[")[0]
        for _, name, _, _ in Formatter().parse(template)
        if name
    }


def _check(entry: dict[str, Any], where: str) -> tuple[Rule | None, Outcome | None, list[str]]:
    problems = []
    try:
        on_fail: Outcome | None = Outcome(str(entry.get("on_fail")))
    except ValueError:
        on_fail = None
    if on_fail not in ON_FAIL:
        problems.append(f"{where}: on_fail must be reject or conditional, not "
                        f"{entry.get('on_fail')!r}")
    try:
        rule = Rule.model_validate({k: v for k, v in entry.items() if k != "on_fail"})
    except ValidationError as e:
        fields = ", ".join(".".join(map(str, err["loc"])) for err in e.errors())
        return None, on_fail, [*problems, f"{where}: invalid {fields}"]

    unknown = set(rule.required_facts) - FACTS
    if unknown:
        problems.append(f"{where}: unknown required_facts {sorted(unknown)}")
    loose = _placeholders(rule.explanation_template) - set(rule.required_facts)
    if loose:
        problems.append(f"{where}: explanation_template uses {sorted(loose)}, "
                        "which are not in required_facts")
    prefixes = SOURCE_REF_PREFIXES[rule.source]
    if not rule.source_ref or not rule.source_ref.startswith(prefixes):
        problems.append(f"{where}: {rule.source.value} rule needs a source_ref starting "
                        f"{' or '.join(prefixes)}, not {rule.source_ref!r}")
    return rule, on_fail, problems


def load_register(path: Path = REGISTER) -> tuple[list[Rule], dict[str, Outcome]]:
    """The rules in register order, and the outcome each gives when it fails.
    Raises ValueError naming every problem in the file."""
    try:
        entries = tomllib.loads(path.read_text(encoding="utf-8")).get("rule", [])
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"{path.name}: not valid TOML: {e}") from e

    rules: list[Rule] = []
    on_fail: dict[str, Outcome] = {}
    problems: list[str] = [] if entries else [f"{path.name}: no [[rule]] entries"]
    for i, entry in enumerate(entries, start=1):
        where = f"{path.name} rule {i} ({entry.get('rule_id', '?')})"
        rule, outcome, found = _check(entry, where)
        problems += found
        if rule is None:
            continue
        if rule.rule_id in {r.rule_id for r in rules}:
            problems.append(f"{where}: duplicate rule_id {rule.rule_id}")
            continue
        rules.append(rule)
        if outcome is not None:
            on_fail[rule.rule_id] = outcome
    if problems:
        raise ValueError("rule register is invalid:\n  " + "\n  ".join(problems))
    return rules, on_fail
