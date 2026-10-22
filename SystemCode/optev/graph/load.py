"""Load contract objects into the graph (#25, design §4.5).

`rows()` turns a bundle of contracts into batches of parameter rows, in the design's order.
All the logic lives there, so it is tested without a database. `load()` only sends each
batch through one fixed MERGE statement, 500 rows at a time, so a re-run updates nodes in
place instead of duplicating them.

The bundle is `optev.sample.Sample`: the sample fills one today, and the Postgres reader
behind `load_all` fills the same shape once the database is live (#2).
"""

from dataclasses import dataclass, field
from typing import Any

from optev.contracts import CandidateSite, EstimateKind, SupplyState
from optev.sample import Sample

from . import schema as S
from .ddl import Session

BATCH_SIZE = 500
WITH_SUPPLY = {SupplyState.SUPPLY_ACTIVE, SupplyState.SUPPLY_IDLE}

Row = dict[str, Any]


@dataclass
class Batch:
    name: str
    """The node label, or `Start-TYPE->End` for a relationship."""
    cypher: str
    rows: list[Row] = field(default_factory=list)


def node_cypher(label: str, extra_label: str | None = None) -> str:
    key = S.node(label).key
    tag = f" SET n:{extra_label}" if extra_label else ""
    return f"UNWIND $rows AS r MERGE (n:{label} {{{key}: r.key}}) SET n += r.props{tag}"


def rel_cypher(spec: S.RelSpec) -> str:
    a, b = S.node(spec.start).key, S.node(spec.end).key
    return (
        f"UNWIND $rows AS r MATCH (a:{spec.start} {{{a}: r.a}}) "
        f"MATCH (b:{spec.end} {{{b}: r.b}}) "
        f"MERGE (a)-[x:{spec.type}]->(b) SET x += r.props"
    )


def rel_spec(type_: str, start: str, end: str) -> S.RelSpec:
    return next(
        r for r in S.RELATIONSHIPS if (r.type, r.start, r.end) == (type_, start, end)
    )


class _Builder:
    """Collects batches in the order they are first used, and only emits a relationship
    when both ends are in the bundle, so nothing points at a node that does not exist."""

    def __init__(self, extra_label: str | None) -> None:
        self.extra_label = extra_label
        self.batches: dict[str, Batch] = {}
        self.keys: dict[str, set[str]] = {}

    def node(self, label: str, values: Row) -> str:
        spec = S.node(label)
        key = str(values[spec.key])
        # None removes the property on re-load: a missing value is absent, never 0.
        props = {p: values.get(p) for p in spec.properties}
        batch = self.batches.setdefault(label, Batch(label, node_cypher(label, self.extra_label)))
        batch.rows.append({"key": key, "props": props})
        self.keys.setdefault(label, set()).add(key)
        return key

    def rel(self, type_: str, start: str, a: str | None, end: str, b: str | None,
            values: Row | None = None) -> None:
        if a not in self.keys.get(start, set()) or b not in self.keys.get(end, set()):
            return
        spec = rel_spec(type_, start, end)
        name = f"{start}-{type_}->{end}"
        batch = self.batches.setdefault(name, Batch(name, rel_cypher(spec)))
        props = {p: (values or {}).get(p) for p in spec.properties}
        batch.rows.append({"a": a, "b": b, "props": props})


def _flat(model: Any) -> Row:
    """model_dump with enums as strings and the coordinate flattened to lat/lon."""
    values: Row = model.model_dump(mode="json")
    coord = values.pop("coord", None)
    if coord:
        values.update(coord)
    return values


def _ref_label(ref: str | None) -> str | None:
    for prefix, label in (
        (S.DATASET_PREFIX, "Dataset"),
        (S.DOCUMENT_PREFIX, "Document"),
        (S.ASSUMPTION_PREFIX, "Assumption"),
    ):
        if ref and ref.startswith(prefix):
            return label
    return None


def _many(data: Any, plural: str, single: str) -> list[Any]:
    """The sample holds one plan and one report; Postgres may hold any number (or none)."""
    if hasattr(data, plural):
        return list(getattr(data, plural))
    one = getattr(data, single, None)
    return [one] if one is not None else []


def rows(data: Sample, extra_label: str | None = None) -> list[Batch]:
    """Every batch to send, in the order of design §4.5. Raw readings and per-bin estimates
    are never loaded: the graph explains decisions, it does not store measurements."""
    return list(_build(data, extra_label).batches.values())


def stale_links(data: Sample) -> list[Batch]:
    """For every node this bundle loads, delete its outgoing relationships of each declared
    type before they are re-merged. Without this a re-run keeps links the new data dropped:
    a site removed from a re-solved plan would still look allocated."""
    keys = _build(data, None).keys
    out = []
    for spec in S.RELATIONSHIPS:
        starts = sorted(keys.get(spec.start, set()))
        if not starts:
            continue
        key = S.node(spec.start).key
        cypher = (f"UNWIND $rows AS r MATCH (a:{spec.start} {{{key}: r.key}})"
                  f"-[x:{spec.type}]->(:{spec.end}) DELETE x")
        out.append(Batch(f"clear {spec.start}-{spec.type}->{spec.end}", cypher,
                         [{"key": k} for k in starts]))
    return out


def _build(data: Sample, extra_label: str | None) -> "_Builder":
    g = _Builder(extra_label)

    # Reference nodes first, so every later relationship can see its target.
    for area in data.planning_areas:
        g.node("PlanningArea", _flat(area))
    for ref in data.references.get("datasets", []):
        g.node("Dataset", ref)
    for ref in data.references.get("documents", []):
        g.node("Document", ref)
    for ref in data.references.get("assumptions", []):
        g.node("Assumption", ref)
    for code in S.SOURCE_CLASSES:  # seeded by apply_schema; listed so rules can link
        g.keys.setdefault("SourceClass", set()).add(code.value)

    for cp in data.car_parks:
        k = g.node("CarPark", _flat(cp))
        g.rel("IN_AREA", "CarPark", k, "PlanningArea", cp.planning_area)
    for st in data.stations:
        k = g.node("Station", _flat(st))
        g.rel("IN_AREA", "Station", k, "PlanningArea", st.planning_area)
    for c in data.connectors:
        k = g.node("Connector", _flat(c))
        g.rel("PART_OF", "Connector", k, "Station", c.station_id)
    sites: dict[str, CandidateSite] = {}
    for site in data.sites:
        k = g.node("CandidateSite", _flat(site))
        sites[k] = site
        g.rel("IN_AREA", "CandidateSite", k, "PlanningArea", site.planning_area)
        g.rel("AT", "CandidateSite", k, "CarPark", site.car_park_id)
    for near in data.near:
        g.rel("NEAR", "Station", near["station_id"], "CandidateSite", near["site_id"], near)

    supplied: dict[str, list[str]] = {}
    for ind in data.indicators:
        values = _flat(ind)
        values["indicator_id"] = S.indicator_key(ind.site_id, ind.window_start, ind.window_end)
        k = g.node("Indicator", values)
        g.rel("HAS_INDICATOR", "CandidateSite", ind.site_id, "Indicator", k)
        g.rel("DERIVED_FROM", "Indicator", k, "Dataset", S.EV_FEED)
        if ind.supply_state in WITH_SUPPLY:
            supplied.setdefault(ind.site_id, []).append(k)
    for est in data.estimates:
        if est.time_bin != "all":
            continue
        values = _flat(est)
        values["estimate_id"] = S.estimate_key(est.site_id, est.time_bin)
        k = g.node("DemandEstimate", values)
        g.rel("HAS_DEMAND", "CandidateSite", est.site_id, "DemandEstimate", k)
        for ind_key in supplied.get(est.site_id, []):
            g.rel("BASED_ON", "DemandEstimate", k, "Indicator", ind_key)
        g.rel("ASSUMES", "DemandEstimate", k, "Assumption", S.SESSION_ASSUMPTION)
        if est.kind is EstimateKind.LOWER_BOUND:
            g.rel("ASSUMES", "DemandEstimate", k, "Assumption", S.RELIABILITY_ASSUMPTION)

    for rule in data.rules:
        values = _flat(rule)
        on_fail = data.rule_on_fail.get(rule.rule_id)
        values["on_fail"] = on_fail.value if on_fail else None
        k = g.node("Rule", values)
        g.rel("FROM_SOURCE", "Rule", k, "SourceClass", rule.source.value)
        target = _ref_label(rule.source_ref)
        if target:
            type_ = {"Dataset": "READS", "Document": "CITES", "Assumption": "ASSUMES"}[target]
            g.rel(type_, "Rule", k, target, rule.source_ref)

    for sc in data.scenarios:
        k = g.node("Scenario", _flat(sc))
        for pick in sc.planned:
            g.rel("PLANS", "Scenario", k, "CandidateSite", pick.site_id, _flat(pick))

    for d in data.decisions:
        values = _flat(d)
        values["decision_id"] = S.decision_key(d.site_id, d.scenario_id)
        k = g.node("Decision", values)
        g.rel("ABOUT", "Decision", k, "CandidateSite", d.site_id)
        g.rel("UNDER", "Decision", k, "Scenario", d.scenario_id)
        for r in d.results:
            g.rel("EVALUATED", "Decision", k, "Rule", r.rule_id,
                  {"verdict": S.verdict(r), "detail": r.detail})

    for a in _many(data, "allocations", "allocation"):
        values = _flat(a)
        values["allocation_id"] = S.allocation_key(
            a.scenario_id, a.planning_area, a.requested_connectors, a.budget
        )
        k = g.node("Allocation", values)
        g.rel("UNDER", "Allocation", k, "Scenario", a.scenario_id)
        for item in a.items:
            g.rel("ALLOCATES", "Allocation", k, "CandidateSite", item.site_id, _flat(item))

    for rep in _many(data, "infeasibilities", "infeasibility"):
        values = _flat(rep)
        values["report_id"] = S.infeasibility_key(
            rep.scenario_id, rep.planning_area, rep.requested_connectors
        )
        k = g.node("Infeasibility", values)
        g.rel("FOR", "Infeasibility", k, "Scenario", rep.scenario_id)
        for area_code in rep.affected_areas:
            g.rel("AFFECTS", "Infeasibility", k, "PlanningArea", area_code)

    return g


def load(data: Sample, session: Session, extra_label: str | None = None) -> dict[str, int]:
    """MERGE the bundle into the graph. Returns rows sent per node label or relationship.
    Run `apply_schema` first: the uniqueness constraints are what make MERGE safe.

    The loaded nodes' outgoing links are replaced, not added to: they are deleted first, so
    the graph matches the bundle after every run. Nodes the bundle does not mention are left
    alone (use `clear_sample` to remove the sample)."""
    counts: dict[str, int] = {}
    for batch in stale_links(data):
        for i in range(0, len(batch.rows), BATCH_SIZE):
            session.run(batch.cypher, {"rows": batch.rows[i : i + BATCH_SIZE]}).consume()
    for batch in rows(data, extra_label):
        for i in range(0, len(batch.rows), BATCH_SIZE):
            session.run(batch.cypher, {"rows": batch.rows[i : i + BATCH_SIZE]}).consume()
        counts[batch.name] = len(batch.rows)
    return counts


def load_all(database_url: str) -> dict[str, int]:
    """Design §4.5: rebuild the graph from Postgres after a pipeline run. Reads every pipeline
    table into one bundle (graph.read) and MERGEs it; the sample, if loaded, is left alone."""
    from .client import driver
    from .ddl import apply_schema
    from .read import read_bundle

    data = read_bundle(database_url)
    with driver() as d, d.session() as s:
        apply_schema(s)
        return load(data, s)  # type: ignore[arg-type]  # GraphBundle has Sample's fields


def clear_sample(session: Session) -> int:
    """Remove everything loaded from optev.sample, before real data goes in."""
    query = f"MATCH (n:{S.SAMPLE_LABEL}) DETACH DELETE n RETURN count(*) AS n"
    record = session.run(query).single()
    return int(record["n"]) if record else 0
