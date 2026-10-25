"""The part of the knowledge graph an answer used, as nodes and edges for the Ask Why page.

Built only from the rows the fixed query returned (optev.graph.retrieve), so the picture shows
exactly what the answer rests on: the site, its decision, each rule and the document it cites,
the measurements and the dataset they came from, the demand estimate and its assumptions, and
the plan. Labels are words (optev.app.labels); ids stay inside. Pure, tested without Streamlit.
"""

from dataclasses import dataclass, field
from typing import Any

from optev.app import labels as L
from optev.app.data import AppData

# group -> (fill, border); outcome colours match the Site Map
COLOURS = {
    "site": ("#0097B2", "#007A90"), "area": ("#5B6B73", "#46545B"),
    "accept": ("#1A9641", "#137533"), "conditional": ("#F0A000", "#C98600"),
    "defer": ("#8C8C8C", "#6E6E6E"), "reject": ("#D7302C", "#B02420"),
    "source": ("#6C5CE7", "#5546C9"), "measure": ("#2D9CDB", "#1F80B8"),
    "demand": ("#14B8A6", "#0E9384"), "assumption": ("#A0A8AD", "#848C91"),
    "plan": ("#0F766E", "#2FA35A"),
}
VERDICT = {"passed": "accept", "failed": "reject", "unevaluated": "defer"}
LEGEND = [("site", "Site"), ("accept", "Passed / Accept"), ("conditional", "Conditional"),
          ("reject", "Failed / Reject"), ("defer", "Missing data / Defer"),
          ("source", "Source document or dataset"), ("measure", "Measured"),
          ("demand", "Inferred demand"), ("assumption", "Declared assumption"),
          ("plan", "Recommended plan"), ("area", "Planning area")]


@dataclass
class Graph:
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: list[dict[str, Any]] = field(default_factory=list)

    def node(self, key: str, label: str, group: str, title: str = "", size: int = 18) -> str:
        if key not in self.nodes:
            fill, border = COLOURS[group]
            self.nodes[key] = {"id": key, "label": label, "group": group, "title": title,
                               "color": {"background": fill, "border": border}, "size": size}
        return key

    def edge(self, a: str, b: str, label: str) -> None:
        if a in self.nodes and b in self.nodes and a != b:
            self.edges.append({"from": a, "to": b, "label": label})


def _wrap(text: str, width: int = 22) -> str:
    words, lines, line = text.split(), [], ""
    for w in words:
        if len(line) + len(w) + 1 > width and line:
            lines.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    return "\n".join([*lines, line])


def _source(g: Graph, data: AppData, ref: str | None, title: str | None) -> str | None:
    if not ref:
        return None
    name = title or L.words(data, ref)
    return g.node(f"src:{ref}", _wrap(name, 26), "source", name, 14)


def _site(g: Graph, data: AppData, row: dict[str, Any]) -> str:
    sid = row["site_id"]
    outcome = row.get("outcome")
    kind = L.KINDS.get(row.get("kind", ""), "Site")
    title = (f"{kind} · {row.get('total_lots', '?')} car lots · "
             f"{row.get('existing_connectors', 0)} points today")
    key = g.node(f"site:{sid}", _wrap(L.site(data, sid, with_area=False)), "site", title, 30)
    if row.get("planning_area"):
        area = g.node(f"area:{row['planning_area']}", L.area(data, row["planning_area"]), "area",
                      "Planning area", 14)
        g.edge(key, area, "in")
    if outcome:
        dec = g.node(f"dec:{sid}", f"Decision\n{outcome.title()}", outcome,
                     "The rules engine's outcome for this site", 22)
        g.edge(key, dec, "decided")
        return dec
    return key


def _rules(g: Graph, data: AppData, parent: str, rules: list[dict[str, Any]]) -> None:
    for r in rules:
        rid = r.get("rule_id")
        if not rid:
            continue
        verdict = VERDICT.get(str(r.get("verdict")), "defer")
        title = L.detail(r.get("condition") or "") + (f" ({L.detail(r['detail'])})"
                                                      if r.get("detail") else "")
        rule = g.node(f"rule:{parent}:{rid}", _wrap(L.rule(rid), 18), verdict, title, 16)
        g.edge(parent, rule, str(r.get("verdict") or "checked"))
        src = _source(g, data, r.get("evidence_id") or r.get("source_ref"), r.get("evidence"))
        if src:
            g.edge(rule, src, "cites")


def build(question_type: str | None, rows: list[dict[str, Any]], data: AppData) -> Graph:
    g = Graph()
    if question_type == "area_saturation":
        hub = g.node("hub", "Singapore", "site", "All planning areas with chargers", 26)
        for r in rows[:8]:
            area = g.node(f"area:{r['planning_area']}",
                          f"{L.area(data, r['planning_area'])}\n{r['max_saturated_fraction']:.0%}"
                          " full at peak", "measure",
                          f"{r['sites_with_chargers']} sites with chargers", 16)
            g.edge(hub, area, "busiest")
        return g
    if question_type == "rule_sources":
        for r in rows:
            rule = g.node(f"rule:{r['rule_id']}", _wrap(L.rule(r["rule_id"]), 18), "accept",
                          L.detail(r.get("condition") or ""), 24)
            src = _source(g, data, r.get("source_ref"), r.get("evidence"))
            if src:
                g.edge(rule, src, "cites")
            for key, label, group in (("sites_passed", "passed", "accept"),
                                      ("sites_failed", "failed", "reject"),
                                      ("sites_unevaluated", "missing data", "defer")):
                if r.get(key) is not None:
                    n = g.node(f"count:{key}", f"{r[key]:,} sites\n{label}", group, "", 14)
                    g.edge(rule, n, label)
        return g
    for row in rows:
        if "site_id" not in row:
            continue
        hub = _site(g, data, row)
        site = f"site:{row['site_id']}"
        _rules(g, data, hub, row.get("rules") or row.get("rules_not_passed") or [])
        for ind in row.get("indicators") or []:
            m = g.node(f"ind:{ind.get('indicator_id')}",
                       f"Measured week\n{(ind.get('utilisation') or 0):.0%} in use", "measure",
                       "Observed 7–14 Oct 2026", 16)
            g.edge(site, m, "measured")
            src = _source(g, data, ind.get("dataset_id"), ind.get("dataset"))
            if src:
                g.edge(m, src, "from")
        for d in row.get("demand") or []:
            prefix = "at least " if d.get("kind") == "lower_bound" else ""
            est = g.node(f"dem:{d.get('estimate_id')}",
                         f"Demand\n{prefix}{d.get('arrivals_per_hour', 0):.2f} / hour", "demand",
                         L.detail(d.get("note") or ""), 18)
            g.edge(site, est, "demand")
            for ind_id in d.get("based_on") or []:
                g.edge(est, f"ind:{ind_id}", "based on")
            for a in d.get("assumptions") or []:
                asm = g.node(f"asm:{a.get('assumption_id')}",
                             _wrap(f"{a.get('name')}: {a.get('value')} {a.get('unit') or ''}", 20),
                             "assumption", "Declared assumption", 12)
                g.edge(est, asm, "assumes")
        for a in row.get("assumptions") or []:
            asm = g.node(f"asm:{a.get('assumption_id')}",
                         _wrap(f"{a.get('name')}: {a.get('value')} {a.get('unit') or ''}", 20),
                         "assumption", str(a.get("source_ref") or ""), 14)
            g.edge(site, asm, "assumes")
        for p in row.get("allocated") or []:  # one node per plan; each site's share on its link
            name = L.plan_name(str(p.get("allocation_id"))) or "Recommended plan"
            plan = g.node(f"plan:{p.get('allocation_id')}", _wrap(name.replace("The ", ""), 18),
                          "plan", "The optimiser's recommended plan", 22)
            g.edge(site, plan, f"{p.get('connectors')} new points")
    return g


def headline(question_type: str | None, rows: list[dict[str, Any]], data: AppData
             ) -> list[tuple[str, str, str]]:
    """(place, outcome, what happens) per site the answer is about, for the answer card."""
    out = []
    for row in rows:
        if "site_id" not in row or question_type == "assumptions_used":
            continue
        planned = sum(int(p.get("connectors") or 0) for p in row.get("allocated") or [])
        outcome = str(row.get("outcome") or "")
        what = (f"{planned} new points recommended" if planned else
                {"accept": "eligible, not in the current plan",
                 "conditional": "eligible once a condition is confirmed",
                 "defer": "waiting for missing data", "reject": "not eligible"}.get(outcome, ""))
        out.append((L.site(data, row["site_id"]), outcome, what))
    return out


def points(text: str) -> list[str]:
    """The model's answer as separate points: one sentence each, decimals kept intact."""
    import re

    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(])", text.strip())
    return [p.strip() for p in parts if p.strip()]
