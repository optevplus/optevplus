"""Words for the screen. Ids and codes stay inside the system (joins, graph, citations, tests);
everything a person reads goes through here, so no page ever shows `hdb:A76`, `R03`, `AM`,
`no_supply` or a snake_case header. Pure functions over AppData, tested without Streamlit.
"""

import re
from collections.abc import Iterable, Mapping
from typing import Any

from optev.app.data import AppData

RULE_NAMES = {
    "R01": "Car Lots Published",
    "R02": "Basement Fire Safety",
    "R03": "Room for Another Point",
    "R04": "Chargers in Use",
    "R05": "Inside a Planning Area",
    "R06": "Power Capacity Confirmed",
}
KINDS = {
    "hdb_car_park": "HDB Car Park",
    "public_car_park": "Public Car Park",
    "hawker_centre": "Hawker Centre",
    "community_facility": "Community Club",
    "petrol_station": "Petrol Station",
    "existing_station": "Charging Station",
}
SUPPLY = {
    "supply_active": "Active Chargers",
    "supply_idle": "Idle Chargers",
    "no_supply": "No Chargers",
    "unobserved": "Not Observed",
}
FACTS = {
    "total_lots": "car lots", "existing_connectors": "existing points",
    "car_park_type": "car park type", "supply_state": "supply state", "kind": "site type",
    "planning_area": "planning area", "room": "room",
    "community_facility": "community club", "hdb_car_park": "HDB car park",
    "public_car_park": "public car park", "hawker_centre": "hawker centre",
}
HEADERS = {
    "rank": "Rank", "demand_per_h": "Demand per Hour", "arrivals_per_h": "Arrivals per Hour",
    "active_points": "Active Points", "saturated_share": "Time Full",
    "coverage": "Observation Coverage", "new_points": "New Points",
    "existing_points": "Existing Points", "existing points": "Existing Points",
    "new points": "New Points", "demand / h": "Demand per Hour",
    "drivers rescued / h": "Drivers Rescued per Hour", "cost SGD": "Cost (SGD)",
    "planned already": "Already Planned", "room left after": "Room Left After",
    "to confirm first": "To Confirm First", "if it fails": "If It Fails",
    "source type": "Source Type", "reads as": "Reads As", "demand kind": "Estimate Type",
    "failing_rules": "Rules Failed", "failed": "Rules Failed",
    "unevaluated": "Missing Data For", "utilisation": "Utilisation", "pattern": "Usage Pattern",
    "arrivals per hour": "Arrivals per Hour", "total_lots": "Car Lots",
    "existing_connectors": "Existing Points", "connectors": "Points",
}
SMALL = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on", "or", "per", "the",
         "to", "with"}
# columns that only identify or draw a row; the name column replaces the ids
HIDDEN = {"lat", "lon", "colour", "radius", "lower_bound", "cluster", "day", "hour",
          "estimate_id", "allocation_id", "indicator_ids", "based_on", "dataset_id", "doc_id",
          "assumption_id", "url"}
SITE_KEYS = ("site_id", "site", "site_a", "site_b")
ALLOCATION = re.compile(r"^(?P<scn>[a-z]+):(?P<area>[A-Z]+|all):points=(?P<n>\d+|-)"
                        r":budget=(?P<b>[\d.]+|-)$")


def title(words: str) -> str:
    parts = words.replace("_", " ").split()
    return " ".join(w if w.isupper() and len(w) > 1 else
                    (w.lower() if i and w.lower() in SMALL else w[:1].upper() + w[1:])
                    for i, w in enumerate(parts))


_INDEX: dict[int, tuple[AppData, dict[str, Any], dict[str, str]]] = {}


def _index(data: AppData) -> tuple[dict[str, Any], dict[str, str]]:
    """Sites and area names by id, built once per data bundle (tables have thousands of rows)."""
    hit = _INDEX.get(id(data))
    if hit is None or hit[0] is not data:
        hit = (data, {s.site_id: s for s in data.sites},
               {a.code: title(a.name.lower()) for a in data.planning_areas})
        _INDEX[id(data)] = hit
    return hit[1], hit[2]


def area(data: AppData, code: str | None) -> str:
    if not code:
        return "No Planning Area"
    return _index(data)[1].get(code, code)


def site(data: AppData, site_id: str | None, with_area: bool = True) -> str:
    """A place, never an id: "Blk 613A Ang Mo Kio Avenue 4, Ang Mo Kio"."""
    if not site_id:
        return "Unknown site"
    found = _index(data)[0].get(site_id)
    name = data.site_names.get(site_id)
    if not name:
        kind = KINDS.get(found.kind.value, "Site") if found else "Site"
        name = f"Unnamed {kind}"
    place = area(data, found.planning_area) if found and with_area else ""
    return f"{name}, {place}" if place and place not in name else name


def rule(rule_id: str | None) -> str:
    return RULE_NAMES.get(rule_id or "", rule_id or "")


def rules(ids: Any) -> str:
    if not ids:
        return ""
    items = ids if isinstance(ids, (list, tuple, set)) else re.split(r",\s*", str(ids))
    return ", ".join(rule(i) for i in items if i)


def time_bin(code: str) -> str:
    if code == "all":
        return "Daily Average"
    day, _, hour = code.partition("-")
    return f"{'Weekday' if day == 'wd' else 'Weekend'}, {hour}:00"


def detail(text: Any) -> Any:
    if not isinstance(text, str):
        return text
    from optev.assumptions import IDLE_BELOW, MAX_SHARE_OF_LOTS

    text = text.replace("MAX_SHARE_OF_LOTS", f"{MAX_SHARE_OF_LOTS.value:.0%}").replace(
        "IDLE_BELOW", f"{IDLE_BELOW.value:.0%}")
    for fact, words in FACTS.items():
        text = re.sub(rf"\b{fact}\b", words, text)
    return text


def header(key: str) -> str:
    """'utilisation (observed)' -> 'Utilisation · Observed'."""
    m = re.match(r"^(.*?)\s*\((observed|inferred|recommended|planned|estimate|declared)\)$", key)
    base, layer = (m.group(1), m.group(2)) if m else (key, None)
    words = HEADERS.get(base, title(base))
    return f"{words} · {layer.title()}" if layer else words


def reference(data: AppData, ref_id: str) -> str:
    ref = data.references.get(ref_id)
    if ref:
        return str(ref.get("title") or ref.get("name") or ref.get("label") or ref_id)
    return ref_id


def plan_name(plan_id: str) -> str | None:
    m = ALLOCATION.match(plan_id)
    if not m:
        return None
    where = "island-wide" if m["area"] == "all" else f"in {m['area']}"
    size = f"{m['n']}-point plan" if m["n"] != "-" else f"SGD {float(m['b']):,.0f} plan"
    return f"The {size} {where}, {m['scn']} scenario"


def words(data: AppData, value: str) -> str:
    """Any id the system uses, as words; other text unchanged."""
    if value in RULE_NAMES:
        return rule(value)
    if value in _index(data)[1]:
        return area(data, value)
    if value.endswith("@all") or "@" in value:
        sid, _, bin_ = value.partition("@")
        return f"{time_bin(bin_)} demand at {site(data, sid, with_area=False)}"
    if value.startswith(("ds-", "doc-", "asm-")):
        return reference(data, value)
    if plan_name(value):
        return plan_name(value) or value
    if value.startswith("observed:"):
        return f"Decision for {site(data, value.split(':', 1)[1], with_area=False)}"
    if value in _index(data)[0]:
        return site(data, value, with_area=False)
    short = [sid for sid in _index(data)[0] if sid.rsplit(":", 1)[-1] == value]
    if len(short) == 1:  # the model cited "A76" for hdb:A76, as the evidence check allows
        return site(data, short[0], with_area=False)
    return value


def table(rows: Iterable[Mapping[str, Any]], data: AppData) -> list[dict[str, Any]]:
    """Rows from a view module, ready for a person: a Site name column first, ids dropped,
    codes as words, headers in Title Case with their layer."""
    out = []
    for row in rows:
        new: dict[str, Any] = {"Rank": row["rank"]} if "rank" in row else {}
        for key in SITE_KEYS:
            if key in row and isinstance(row[key], str):
                new["Site" if key in ("site_id", "site") else title(key)] = site(data, row[key])
        for key, value in row.items():
            if key in SITE_KEYS or key in HIDDEN or key == "rank":
                continue
            if key == "name" and "planning_area" in row:  # the area's name, already shown
                continue
            if key in ("planning_area", "area"):
                new["Planning Area"] = area(data, value)
            elif key == "kind":
                new["Type"] = KINDS.get(str(value), title(str(value)))
            elif key == "outcome":
                new["Outcome"] = title(str(value)) if value else ""
            elif key in ("failing_rules", "failed", "unevaluated", "to confirm first"):
                new[header(key)] = rules(value)
            elif key == "rule":
                new["Rule"] = rule(value)
            elif key.startswith("supply_state"):
                new[header(key).replace("Supply State", "Chargers")] = SUPPLY.get(value, value)
            elif key.startswith("pattern") and isinstance(value, str):
                new[header(key)] = value[:1].upper() + value[1:]
            elif key == "time_bin":
                new["When"] = time_bin(value)
            elif key == "site_ids":
                ids = [i for i in re.split(r",\s*", str(value)) if i][:3]
                new["Example Sites"] = "; ".join(site(data, i, with_area=False) for i in ids)
            elif key in ("detail", "result", "source type", "method", "condition"):
                new[header(key)] = title(detail(value)) if key == "source type" else detail(value)
            elif isinstance(value, str) and (value in RULE_NAMES or "@" in value
                                             or value.startswith(("ds-", "doc-", "asm-"))
                                             or plan_name(value)):
                new[header(key)] = words(data, value)
            else:
                new[header(key)] = value
        out.append(new)
    return out


def _aliases(data: AppData) -> dict[str, str]:
    """Lower-case name -> site id. A shared address ("... (2,010 lots)") is also reachable by the
    bare address, which then means the larger car park."""
    lots = {s.site_id: s.total_lots or 0 for s in data.sites}
    out: dict[str, str] = {}
    for sid, name in sorted(data.site_names.items(), key=lambda kv: lots.get(kv[0], 0)):
        out[name.lower()] = sid
        out[re.sub(r" \([\d,]+ lots\)$| \(\d+\)$", "", name).lower()] = sid  # larger wins
    return out


def resolve_names(question: str, data: AppData) -> str:
    """Let people ask by place: known site names in the question become their ids (longest
    first, at most two for a comparison), so the fixed question patterns, which match ids,
    still apply. Questions that already use ids are unchanged."""
    aliases = _aliases(data)
    for _ in range(2):
        low = question.lower()
        hits = [(name, sid) for name, sid in aliases.items() if len(name) > 6 and name in low]
        if not hits:
            break
        name, sid = max(hits, key=lambda h: len(h[0]))
        start = low.find(name)
        question = question[:start] + sid + question[start + len(name):]
    return question


MONEY = re.compile(r"\b(costs?|costing|budget|price|priced)(\s+(?:of|at|is|was|about|around))?"
                   r"\s+(?:S\$\s?|SGD\s?|\$)?(\d+(?:,\d{3})*(?:\.\d+)?)", re.I)
TRAILING_ZERO = re.compile(r"(?<![\w.])(\d+)\.0+(?![\d])")
COUNTED = re.compile(r"\s+(?:car\s+|parking\s+|new\s+|charging\s+)*(?:lots?|sites?|points?|"
                     r"connectors?|chargers?|drivers?|arrivals?|readings?|spaces?)\b", re.I)
BIG = re.compile(r"(?<![\w.,$/:-])(\d{4,})(?![\w,.%/:-]|\.\d)")


def tidy_numbers(text: str) -> str:
    """The model copies numbers as stored ("a cost of 46250.0", "2010 lots"). Show them as a
    person would: money as S$46,250, no trailing .0, thousands with commas. Years (1900-2100)
    stay as written unless a count follows ("2010 parking lots"). Display only: the evidence
    check runs on the model's own text."""
    text = MONEY.sub(lambda m: f"{m[1]}{m[2] or ''} S${float(m[3].replace(',', '')):,.0f}",
                     text)
    text = TRAILING_ZERO.sub(r"\1", text)
    def group(m: re.Match[str]) -> str:
        n = int(m[1])
        counted = COUNTED.match(m.string, m.end())  # "2010 lots" is a count, not a year
        return m[1] if 1900 <= n <= 2100 and not counted else f"{n:,}"

    return BIG.sub(group, text)


def readable_answer(text: str, data: AppData) -> tuple[str, list[str]]:
    """An answer with its [id] citations taken out and every id written as words; the cited
    sources come back as a list of names to show under it."""
    cited = list(dict.fromkeys(re.findall(r"\[([^\]]+)\]", text)))
    clean = tidy_numbers(re.sub(r"\s*\[[^\]]+\]", "", text))  # before ids become names
    ids = sorted({sid for sid in _index(data)[0] if sid in clean}, key=len, reverse=True)
    for sid in ids:
        clean = re.sub(rf"(?<![\w:]){re.escape(sid)}(?![\w])",
                       site(data, sid, with_area=False), clean)
    for rid, name in RULE_NAMES.items():
        clean = re.sub(rf"\b{rid}\b", name, clean)
    sources = []
    for c in cited:
        for part in re.split(r",\s*", c.strip().strip('"')):
            part = part.split(":", 1)[1].strip().strip('"') if re.match(r"^\w+_id:", part) else part
            sources.append(words(data, part))
    return clean, list(dict.fromkeys(sources))


def text(value: str, data: AppData) -> str:
    """Free text that may mention ids (section titles, captions): ids become words."""
    for sid in sorted({sid for sid in _index(data)[0] if sid in value}, key=len, reverse=True):
        value = value.replace(sid, site(data, sid, with_area=False))
    return value
