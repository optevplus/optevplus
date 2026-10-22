"""Rules: register (#17), engine (#18) and eligibility screening (#19). SYSTEM_DESIGN.md §4.4.

The register is data, not code: `register.toml` holds one entry per rule with every `Rule`
field plus `on_fail`, and `load_register` refuses a broken one. Each rule's test lives in
`CHECKS`. `evaluate` runs every rule over a site's facts and applies the outcome policy;
`screen` does that for every candidate site and reports the funnel; `write_decisions` stores
the result; `screen_all` runs both against Postgres (`python -m optev.reasoning screen`).
"""

import logging
import math
import tomllib
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from string import Formatter
from typing import Any

from psycopg import Cursor
from pydantic import ValidationError

from optev.assumptions import MAX_SHARE_OF_LOTS
from optev.contracts import (
    CandidateSite,
    CarPark,
    Decision,
    Outcome,
    Rule,
    RuleResult,
    RuleSource,
    SiteIndicators,
    SiteKind,
    SupplyState,
)

log = logging.getLogger(__name__)

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


# Register (#17) -------------------------------------------------------------------------

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
        rule, fails_to, found = _check(entry, where)
        problems += found
        if rule is None:
            continue
        if rule.rule_id in {r.rule_id for r in rules}:
            problems.append(f"{where}: duplicate rule_id {rule.rule_id}")
            continue
        rules.append(rule)
        if fails_to is not None:
            on_fail[rule.rule_id] = fails_to
    if problems:
        raise ValueError("rule register is invalid:\n  " + "\n  ".join(problems))
    return rules, on_fail


# Facts (#19) ----------------------------------------------------------------------------

Facts = dict[str, object]
CONTEXT_FACTS = ("land_use", "amenities_nearby", "nearest_point_m")


def _facts(site: CandidateSite, car_park: CarPark | None, indicators: SiteIndicators | None,
           context: Mapping[str, object]) -> Facts:
    if indicators is not None and indicators.site_id != site.site_id:
        raise ValueError(f"indicators for {indicators.site_id} given for site {site.site_id}")
    facts: Facts = {
        "kind": site.kind,
        "planning_area": site.planning_area,
        "total_lots": site.total_lots,
        "existing_connectors": site.existing_connectors,
        "car_park_type": car_park.car_park_type if car_park else None,
        "supply_state": indicators.supply_state if indicators else None,
        "utilisation": indicators.utilisation if indicators else None,
        **{k: context.get(k) for k in CONTEXT_FACTS},
    }
    # a missing value is absent, never 0 (invariant 2 for utilisation)
    return {k: v for k, v in facts.items() if v is not None}


def site_facts(site: CandidateSite, car_park: CarPark | None,
               indicators: SiteIndicators, context: dict[str, object]) -> dict[str, object]:
    """The facts rules may read about one site. Missing values are left out."""
    return _facts(site, car_park, indicators, context)


# Engine (#18) ---------------------------------------------------------------------------

def _int(facts: Mapping[str, object], key: str) -> int:
    value = facts[key]
    if not isinstance(value, int):
        raise TypeError(f"fact {key} should be an integer, not {value!r}")
    return value


def _room(f: Mapping[str, object]) -> int:
    lots, existing = _int(f, "total_lots"), _int(f, "existing_connectors")
    return max(0, math.floor(MAX_SHARE_OF_LOTS.value * lots) - existing)


# (derived fact, the facts it needs, how to compute it), fired by forward chaining
Derivation = tuple[str, tuple[str, ...], Callable[[Mapping[str, object]], object]]
DERIVED: tuple[Derivation, ...] = (
    ("room", ("total_lots", "existing_connectors"), _room),
)


def _r01(f: Mapping[str, object]) -> tuple[bool, str | None]:
    # capacity is published: present is enough; absent never reaches a check (defer)
    return True, None


CAR_PARK_KINDS = frozenset({SiteKind.HDB_CAR_PARK, SiteKind.PUBLIC_CAR_PARK})


def _r02(f: Mapping[str, object]) -> tuple[bool | None, str | None]:
    # MHA written reply, 8 Sep 2026: "sprinklers are required for enclosed basement carparks",
    # and SCDF requires an isolation switch within 15 m of every EV charging station. No
    # dataset says whether a basement has them, so a basement car park is conditional on
    # confirming them. Only car parks have a type: other sites pass; a car park of unknown
    # type cannot be judged, so it is unevaluated (defer), never assumed safe.
    if f["kind"] not in CAR_PARK_KINDS:
        return True, "not a car park"
    car_park_type = f.get("car_park_type")
    if car_park_type is None:
        return None, "car_park_type missing"
    if "BASEMENT" in str(car_park_type).upper():
        return False, "basement: confirm sprinklers and EV isolation switch"
    return True, None


def _r03(f: Mapping[str, object]) -> tuple[bool, str | None]:
    # existing plus one new point stays within MAX_SHARE_OF_LOTS of the car lots
    return _int(f, "room") >= 1, f"room {f['room']}"


def _r04(f: Mapping[str, object]) -> tuple[bool, str | None]:
    # idle chargers (used under IDLE_BELOW, as the indicators classify them) get no more
    return f["supply_state"] != SupplyState.SUPPLY_IDLE, None


def _r05(f: Mapping[str, object]) -> tuple[bool, str | None]:
    # conform assigns the area by point-in-polygon on MP2025; present means inside one.
    # A site outside every polygon has no planning_area, so it defers as a data gap.
    return True, None


def _r06(f: Mapping[str, object]) -> tuple[bool, str | None]:
    # MOT, 14 Oct 2025: deploy "in carparks with high charging demand, electrical capacity
    # permitting". No dataset reports spare capacity, so it counts as shown only where
    # chargers already run; anywhere else the planner must confirm it first.
    if _int(f, "existing_connectors") >= 1:
        return True, None
    return False, "electrical capacity to be confirmed"


# A check returns (passed, detail). passed is None when a fact the rule needs only for some
# kinds of site is missing; that is unevaluated, exactly like a missing required fact.
Check = Callable[[Mapping[str, object]], tuple[bool | None, str | None]]
CHECKS: dict[str, Check] = {
    "R01": _r01, "R02": _r02, "R03": _r03, "R04": _r04, "R05": _r05, "R06": _r06,
}


def derive(facts: Mapping[str, object]) -> Facts:
    """Add derived facts until none can fire. The facts given are never changed."""
    known = dict(facts)
    fired = True
    while fired:
        fired = False
        for name, needs, compute in DERIVED:
            if name not in known and all(known.get(k) is not None for k in needs):
                known[name] = compute(known)
                fired = True
    return known


def outcome(results: Sequence[RuleResult], on_fail: Mapping[str, Outcome]) -> Outcome:
    """§4.4 policy: reject, then defer, then conditional, then accept."""
    failed = []
    for r in results:
        if r.passed is False:
            if r.rule_id not in on_fail:
                raise ValueError(f"rule {r.rule_id} failed but has no on_fail")
            failed.append(on_fail[r.rule_id])
    if Outcome.REJECT in failed:
        return Outcome.REJECT
    if any(r.passed is None for r in results):
        return Outcome.DEFER
    return Outcome.CONDITIONAL if failed else Outcome.ACCEPT


def evaluate(site_id: str, facts: dict[str, object], rules: list[Rule],
             on_fail: dict[str, Outcome], scenario_id: str | None = None) -> Decision:
    """Every rule, in register order; never stops at the first failure. A rule whose required
    fact is missing is unevaluated (`passed` None), which defers, never rejects."""
    unchecked = [r.rule_id for r in rules if r.rule_id not in CHECKS]
    if unchecked:
        raise ValueError(f"rules with no check in rules.CHECKS: {unchecked}")
    known = derive(facts)
    results = []
    for rule in rules:
        missing = [k for k in rule.required_facts if facts.get(k) is None]
        if missing:
            results.append(RuleResult(rule_id=rule.rule_id, passed=None,
                                      detail=", ".join(f"{k} missing" for k in missing)))
            continue
        passed, detail = CHECKS[rule.rule_id](known)
        results.append(RuleResult(rule_id=rule.rule_id, passed=passed, detail=detail))
    return Decision(site_id=site_id, outcome=outcome(results, on_fail), results=results,
                    scenario_id=scenario_id)


# Screening (#19) ------------------------------------------------------------------------

def _ends(ind: SiteIndicators) -> datetime:
    return datetime.fromisoformat(ind.window_end)  # ISO text in the contract; compare as time


def screen(sites: list[CandidateSite], car_parks: list[CarPark],
           indicators: list[SiteIndicators], context: dict[str, dict[str, object]],
           rules: list[Rule], on_fail: dict[str, Outcome],
           scenario_id: str | None = None) -> tuple[list[Decision], dict[Outcome, int]]:
    """Evaluate every candidate site, each with its latest indicators window. Returns the
    decisions and how many sites got each outcome (all four keys, so the funnel shows)."""
    by_car_park = {cp.car_park_id: cp for cp in car_parks}
    latest: dict[str, SiteIndicators] = {}
    for row in indicators:
        seen = latest.get(row.site_id)
        if seen is None or _ends(row) > _ends(seen):
            latest[row.site_id] = row
    decisions = []
    funnel = dict.fromkeys(Outcome, 0)
    for site in sites:
        ind = latest.get(site.site_id)
        if ind is None:
            log.warning("site %s has no indicators; rules that need them defer", site.site_id)
        car_park = by_car_park.get(site.car_park_id) if site.car_park_id else None
        facts = _facts(site, car_park, ind, context.get(site.site_id, {}))
        decision = evaluate(site.site_id, facts, rules, on_fail, scenario_id)
        decisions.append(decision)
        funnel[decision.outcome] += 1
    log.info("screened %d sites: %s", len(sites),
             ", ".join(f"{o.value} {n}" for o, n in funnel.items()))
    return decisions, funnel


UPSERT_RULE = """INSERT INTO rule (rule_id, condition, source, source_ref, required_facts,
    explanation_template, on_fail) VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (rule_id) DO UPDATE SET condition = EXCLUDED.condition,
    source = EXCLUDED.source, source_ref = EXCLUDED.source_ref,
    required_facts = EXCLUDED.required_facts,
    explanation_template = EXCLUDED.explanation_template, on_fail = EXCLUDED.on_fail"""
UPSERT_DECISION = """INSERT INTO decision (site_id, scenario_id, outcome, decided_at)
    VALUES (%s, %s, %s, now()) ON CONFLICT (site_id, scenario_id) DO UPDATE SET
    outcome = EXCLUDED.outcome, decided_at = EXCLUDED.decided_at"""
CLEAR_RESULTS = "DELETE FROM rule_result WHERE site_id = %s AND scenario_id = %s"
INSERT_RESULT = """INSERT INTO rule_result (site_id, scenario_id, rule_id, passed, detail)
    VALUES (%s, %s, %s, %s, %s)"""
OBSERVED = "observed"  # §3.2: baseline decisions belong to no scenario


def write_decisions(cur: Cursor[Any], rules: list[Rule], on_fail: dict[str, Outcome],
                    decisions: list[Decision]) -> dict[str, int]:
    """Upsert the register into `rule`, then each decision and its rule results. A site's
    earlier results for the same scenario are replaced, so a rerun gives the same tables."""
    cur.executemany(UPSERT_RULE, [
        (r.rule_id, r.condition, r.source.value, r.source_ref, r.required_facts,
         r.explanation_template, on_fail[r.rule_id].value) for r in rules
    ])
    keys = [(d.site_id, d.scenario_id or OBSERVED) for d in decisions]
    cur.executemany(UPSERT_DECISION, [
        (*key, d.outcome.value) for key, d in zip(keys, decisions, strict=True)
    ])
    cur.executemany(CLEAR_RESULTS, keys)
    results = [
        (*key, r.rule_id, r.passed, r.detail)
        for key, d in zip(keys, decisions, strict=True) for r in d.results
    ]
    cur.executemany(INSERT_RESULT, results)
    return {"rule": len(rules), "decision": len(decisions), "rule_result": len(results)}


# Screening the database ------------------------------------------------------------------

READ_SITES = """SELECT site_id, kind, planning_area, car_park_id, total_lots,
    existing_connectors, provenance, ST_Y(geom) AS lat, ST_X(geom) AS lon FROM candidate_site"""
READ_CAR_PARKS = """SELECT car_park_id, name, ST_Y(geom) AS lat, ST_X(geom) AS lon,
    planning_area, total_lots, car_park_type, has_live_feed FROM car_park"""
READ_INDICATORS = """SELECT site_id, window_start, window_end, supply_state, active_connectors,
    utilisation, saturated_fraction, dwell_opportunity, observation_coverage
    FROM site_indicators"""
READ_CONTEXT = "SELECT site_id, land_use, amenities_nearby, nearest_point_m FROM site_context"


def _rows[M: (CandidateSite, CarPark, SiteIndicators)](
    model: type[M], rows: Iterable[Mapping[str, Any]]
) -> list[M]:
    """Contract objects from table rows: coordinates nested, timestamps as ISO text (the
    contract's form). A bad row is logged and skipped."""
    out = []
    for row in rows:
        data = {k: v for k, v in row.items() if k not in ("lat", "lon")}
        if "lat" in row:
            data["coord"] = {"lat": row["lat"], "lon": row["lon"]}
        for key in ("window_start", "window_end"):
            if isinstance(data.get(key), datetime):
                data[key] = data[key].isoformat()
        try:
            out.append(model.model_validate(data))
        except ValidationError as e:
            log.warning("skipped %s row %s: %s", model.__name__, next(iter(row.values()), "?"),
                        e.errors()[0]["msg"])
    return out


def screen_all(database_url: str, scenario_id: str | None = None,
               write: bool = True) -> dict[Outcome, int]:
    """Screen every row of `candidate_site` with its latest `site_indicators` window and its
    `site_context`, write the decisions (unless `write` is False) and return the funnel."""
    import psycopg
    from psycopg.rows import dict_row

    rules, on_fail = load_register()
    with psycopg.connect(database_url, row_factory=dict_row) as conn, conn.cursor() as cur:
        sites = _rows(CandidateSite, cur.execute(READ_SITES))
        car_parks = _rows(CarPark, cur.execute(READ_CAR_PARKS))
        indicators = _rows(SiteIndicators, cur.execute(READ_INDICATORS))
        context = {r["site_id"]: dict(r) for r in cur.execute(READ_CONTEXT)}
        if not indicators:
            log.warning("site_indicators is empty; every rule that needs it will defer")
        decisions, funnel = screen(sites, car_parks, indicators, context, rules, on_fail,
                                   scenario_id)
        if write:
            log.info("wrote %s", write_decisions(cur, rules, on_fail, decisions))
            conn.commit()
    return funnel
