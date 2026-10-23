"""Generate the shared sample data. Deterministic: same seed, same files, on any machine.

    uv run python -m optev.sample.generate        # rewrites optev/sample/data/

Everything is synthetic. Charger readings are simulated from a demand we set, so
`truth.json` is an answer key for the demand-inference tests. Only arithmetic and
`random.random()` are used, never libm functions, so the output is byte-identical
across platforms.
"""

import csv
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SEED = 25
SGT = timezone(timedelta(hours=8))
START = datetime(2026, 10, 1, tzinfo=SGT)
HOURS = 48
SNAP_EVERY = 30  # minutes
MEAN_SESSION_H = 3.0  # the declared assumption the estimates use
COST_PER_POINT = 9_250.0
MAX_SHARE = 0.15  # of car lots, per site
POINTS = 12  # the reference request: 12 new points, island-wide, no budget
# The impossible request: 40 points in Pasir Ris, but a budget that pays for fewer.
OVER_AREA, OVER_POINTS, OVER_BUDGET = "PR", 40, 300_000.0
RELIABLE_UP_TO = 0.93
IDLE_BELOW = 0.05

# Session lengths in minutes and their weights. True mean ~182 min, close to the
# declared 3 h, so the small gap is itself realistic.
DURATIONS = [60, 90, 120, 150, 180, 210, 240, 270, 300, 360]
DUR_WEIGHTS = [2, 3, 4, 5, 6, 5, 4, 3, 1, 1]

# Relative arrival rate by hour (residential: evening; commercial: daytime).
_RES = [
    0.6,
    0.4,
    0.3,
    0.2,
    0.2,
    0.3,
    0.5,
    0.7,
    0.6,
    0.5,
    0.5,
    0.6,
    0.7,
    0.6,
    0.6,
    0.8,
    1.0,
    1.4,
    1.8,
    2.0,
    1.9,
    1.6,
    1.2,
    0.9,
]
_COM = [
    0.1,
    0.05,
    0.05,
    0.05,
    0.05,
    0.1,
    0.3,
    0.8,
    1.4,
    1.8,
    1.9,
    2.0,
    2.0,
    1.9,
    1.9,
    1.8,
    1.6,
    1.4,
    1.2,
    1.0,
    0.7,
    0.5,
    0.3,
    0.2,
]
# Car park occupancy by hour (share of lots in use).
_RES_OCC = [
    0.80,
    0.82,
    0.82,
    0.82,
    0.80,
    0.74,
    0.62,
    0.50,
    0.42,
    0.40,
    0.40,
    0.41,
    0.42,
    0.42,
    0.43,
    0.46,
    0.52,
    0.60,
    0.67,
    0.72,
    0.76,
    0.78,
    0.79,
    0.80,
]
_COM_OCC = [
    0.15,
    0.12,
    0.12,
    0.12,
    0.12,
    0.15,
    0.25,
    0.45,
    0.62,
    0.70,
    0.74,
    0.75,
    0.75,
    0.74,
    0.73,
    0.70,
    0.66,
    0.60,
    0.50,
    0.40,
    0.30,
    0.24,
    0.20,
    0.17,
]

AREAS: list[dict[str, Any]] = [
    {
        "code": "TM",
        "name": "TAMPINES",
        "region": "EAST REGION",
        "centre": (1.3530, 103.9440),
        "spread": (0.012, 0.018),
    },
    {
        "code": "PR",
        "name": "PASIR RIS",
        "region": "EAST REGION",
        "centre": (1.3720, 103.9500),
        "spread": (0.008, 0.015),
    },
]
MSCP, SURF, BASE = "MULTI-STOREY CAR PARK", "SURFACE CAR PARK", "BASEMENT CAR PARK"

# (area, operator type, car park type, total lots, station: (active, never-active, arrivals/h))
CAR_PARKS = [
    ("TM", "hdb", MSCP, 620, (4, 0, 2.6)),
    ("TM", "hdb", MSCP, 540, (8, 1, 4.3)),
    ("TM", "hdb", MSCP, 480, (2, 0, 4.1)),
    ("TM", "hdb", SURF, 210, (2, 0, 9.0)),
    ("TM", "hdb", MSCP, 700, (6, 0, 1.2)),
    ("TM", "hdb", BASE, 380, None),
    ("TM", "hdb", MSCP, 520, None),
    ("TM", "hdb", MSCP, 455, None),
    ("TM", "hdb", SURF, 160, None),
    ("TM", "hdb", MSCP, 590, None),
    ("TM", "hdb", BASE, 330, (4, 0, 2.0)),
    ("TM", "hdb", MSCP, 610, None),
    ("TM", "public", SURF, 24, (3, 0, 0.9)),
    ("TM", "public", MSCP, 900, (4, 0, 0.05)),
    ("TM", "public", MSCP, 750, None),
    ("TM", "hdb", MSCP, 505, None),
    ("TM", "hdb", MSCP, 465, None),
    ("TM", "hdb", SURF, 190, None),
    ("PR", "hdb", MSCP, 560, (4, 0, 3.0)),
    ("PR", "hdb", MSCP, 480, None),
    ("PR", "hdb", MSCP, 520, (2, 0, 1.5)),
    ("PR", "hdb", SURF, 175, None),
    ("PR", "public", MSCP, 640, (6, 0, 2.2)),
    ("PR", "hdb", MSCP, 495, None),
    ("PR", "hdb", MSCP, 430, None),
    ("PR", "hdb", SURF, 150, None),
]
# Candidates that are not car parks: (area, kind, total lots or None, default arrivals/h)
AMENITIES = [
    ("TM", "hawker_centre", None, 1.1),
    ("PR", "community_facility", None, 0.7),
    ("TM", "petrol_station", 12, 1.6),
    ("PR", "petrol_station", None, 1.3),
]

OUT_OF_ORDER = ("SYN-ST-02", 2, 6 * 60, 12 * 60)  # station, connector index, from, to (minutes)
FEED_GAP = ("SYN-ST-05", {20, 21, 22, 23})  # snapshots missing for this station

RULES = [
    {
        "rule_id": "R01",
        "condition": "Car capacity is published for the site",
        "source": "gov_dataset",
        "source_ref": "ds-ura-capacity",
        "required_facts": ["total_lots"],
        "explanation_template": "Capacity is known: {total_lots} car lots.",
    },
    {
        "rule_id": "R02",
        "condition": "A basement car park needs a fire-safety review first",
        "source": "gov_policy",
        "source_ref": "doc-mha-ev-carparks-2026",
        "required_facts": ["car_park_type"],
        "explanation_template": "Basement car park: conditional on a fire-safety review.",
    },
    {
        "rule_id": "R03",
        "condition": "Existing plus one new point stays within 15% of car lots",
        "source": "math_constraint",
        "source_ref": "doc-lta-ev-factsheet-2021",
        "required_facts": ["total_lots", "existing_connectors"],
        "explanation_template": "Room for {room} more points within 15% of {total_lots} lots.",
    },
    {
        "rule_id": "R04",
        "condition": "Sites whose chargers are idle (under 5% use) get no more points",
        "source": "project_assumption",
        "source_ref": "asm-idle-threshold",
        "required_facts": ["supply_state"],
        "explanation_template": "Existing chargers are used {utilisation:.0%} of the time.",
    },
    {
        "rule_id": "R05",
        "condition": "The site lies inside a Master Plan 2025 planning area",
        "source": "gov_dataset",
        "source_ref": "ds-mp2025-areas",
        "required_facts": ["planning_area"],
        "explanation_template": "Planning area: {planning_area}.",
    },
]
ON_FAIL = {"R01": "reject", "R02": "conditional", "R03": "reject", "R04": "reject", "R05": "reject"}

REFERENCES = {
    "datasets": [
        {
            "dataset_id": "ds-lta-evcbatch",
            "name": "EV Charging Points Batch",
            "publisher": "LTA DataMall",
            "url": "https://datamall.lta.gov.sg/content/datamall/en/dynamic-data.html",
        },
        {
            "dataset_id": "ds-hdb-availability",
            "name": "Carpark Availability (HDB)",
            "publisher": "data.gov.sg",
            "url": "https://api.data.gov.sg/v1/transport/carpark-availability",
        },
        {
            "dataset_id": "ds-hdb-info",
            "name": "HDB Carpark Information",
            "publisher": "data.gov.sg",
            "url": "https://data.gov.sg/datasets/d_23f946fa557947f93a8043bbef41dd09/view",
        },
        {
            "dataset_id": "ds-ura-capacity",
            "name": "Capacity of URA Parking Places",
            "publisher": "data.gov.sg",
            "url": "https://data.gov.sg",
        },
        {
            "dataset_id": "ds-mp2025-areas",
            "name": "Master Plan 2025 Planning Area Boundary",
            "publisher": "data.gov.sg (URA)",
            "url": "https://data.gov.sg/datasets/d_2cc750190544007400b2cfd5d7f53209/view",
        },
    ],
    "documents": [
        {
            "doc_id": "doc-lta-ev-safety",
            "title": "Regulating the Safety of EV Chargers",
            "publisher": "LTA",
            "url": "https://www.lta.gov.sg/content/ltagov/en/industry_innovations/technologies/"
            "electric_vehicles/regulating_safety_of_ev_chargers.html",
        },
        {
            "doc_id": "doc-lta-ev-factsheet-2021",
            "title": "Accelerating Nationwide Deployment of EV Charging Points (factsheet)",
            "publisher": "LTA",
            "url": "https://www.lta.gov.sg/content/ltagov/en/newsroom/2021/3/news-release/"
            "Accelerating_nationwide_deployment_of_electric_vehicle_charging_points.html",
        },
        {
            "doc_id": "doc-lta-eccg-2025",
            "title": "Guidelines and FAQs for the EV Common Charger Grant",
            "publisher": "LTA",
            "url": "https://www.lta.gov.sg/content/dam/ltagov/industry_innovations/Technologies/"
            "Electric_Vehicles/PDF/ECCG_Guidelines_and_FAQs_05032025.pdf",
        },
        {
            "doc_id": "doc-mha-ev-carparks-2026",
            "title": "Adequacy of Fire Safety Standards for Electric Vehicles in Enclosed and "
            "Multi-Storey Car Parks (written parliamentary reply, 8 Sep 2026)",
            "publisher": "MHA",
            "url": "https://www.mha.gov.sg/media-room/newsroom/adequacy-of-fire-safety-"
            "standards-for-electric-vehicles-in-enclosed-and-multi-storey-car-parks/",
        },
        {
            "doc_id": "doc-mot-ev-reply-2025",
            "title": "Progress on Installation of EV Chargers in HDB Car Parks and Public Spaces "
            "(written parliamentary reply, 14 Oct 2025)",
            "publisher": "MOT",
            "url": "https://www.mot.gov.sg/news-resources/newsroom/"
            "progress-on-installation-of-ev-chargers-in-hdb-car-parks-and-public-spaces/",
        },
    ],
    "assumptions": [
        {
            "assumption_id": "asm-session-hours",
            "name": "Mean charging session",
            "value": MEAN_SESSION_H,
            "unit": "hours",
            "source_ref": "project assumption, varied in sensitivity tests",
        },
        {
            "assumption_id": "asm-cost-per-point",
            "name": "Cost per charging point",
            "value": COST_PER_POINT,
            "unit": "SGD",
            "source_ref": "doc-lta-eccg-2025, example 3",
        },
        {
            "assumption_id": "asm-idle-threshold",
            "name": "Idle utilisation threshold",
            "value": IDLE_BELOW,
            "unit": "share of time",
            "source_ref": "project assumption",
        },
        {
            "assumption_id": "asm-reliable-up-to",
            "name": "Reliable occupancy limit",
            "value": RELIABLE_UP_TO,
            "unit": "share of time",
            "source_ref": "simulation, to be measured",
        },
    ],
}
SCENARIOS = [("low", 3.26), ("base", 3.65), ("high", 3.99)]


def erlang_b(c: int, a: float) -> float:
    b = 1.0
    for k in range(1, c + 1):
        b = a * b / (k + a * b)
    return b


def occupancy(c: int, a: float) -> float:
    return a * (1 - erlang_b(c, a)) / c


def invert(c: int, rho: float) -> float:
    """Arrivals per hour that would produce occupancy `rho` on `c` points."""
    lo, hi = 1e-9, 1e4
    for _ in range(200):
        mid = (lo + hi) / 2
        if occupancy(c, mid) < rho:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2 / MEAN_SESSION_H


def _norm(w: list[float]) -> list[float]:
    m = sum(w) / len(w)
    return [x / m for x in w]


def _iso(t: datetime) -> str:
    return t.isoformat()


def build(rng: random.Random) -> dict:
    res_w, com_w = _norm(_RES), _norm(_COM)
    snaps = [START + timedelta(minutes=m) for m in range(0, HOURS * 60, SNAP_EVERY)]
    out: dict = {
        "planning_areas": [],
        "car_parks": [],
        "stations": [],
        "connectors": [],
        "sites": [],
        "near": [],
        "indicators": [],
        "estimates": [],
        "decisions": [],
    }
    con_rows: list[list[str]] = []
    cp_rows: list[list[str]] = []
    truth: dict = {
        "note": "Answer key for evaluation only. Never use as a model input.",
        "true_mean_session_minutes": round(
            sum(d * w for d, w in zip(DURATIONS, DUR_WEIGHTS, strict=True)) / sum(DUR_WEIGHTS), 2
        ),
        "sites": {},
    }
    area = {a["code"]: a for a in AREAS}
    for a in AREAS:
        out["planning_areas"].append({k: a[k] for k in ("code", "name", "region")})

    def coord(code: str) -> dict:
        (clat, clon), (dlat, dlon) = area[code]["centre"], area[code]["spread"]
        return {
            "lat": round(clat + rng.uniform(-dlat, dlat), 6),
            "lon": round(clon + rng.uniform(-dlon, dlon), 6),
        }

    site_facts: dict[str, dict] = {}
    n_site = 0
    for i, (code, op, cp_type, lots, station) in enumerate(CAR_PARKS, start=1):
        cp_id, n_site = f"SYN-CP-{i:02d}", n_site + 1
        site_id, xy = f"SYN-S-{n_site:02d}", coord(code)
        residential = op == "hdb"
        out["car_parks"].append(
            {
                "car_park_id": cp_id,
                "name": f"Sample car park {i}",
                "coord": xy,
                "planning_area": code,
                "total_lots": lots,
                "car_park_type": cp_type,
                "has_live_feed": True,
            }
        )
        occ_profile = _RES_OCC if residential else _COM_OCC
        for t in snaps:
            occ = min(0.98, max(0.02, occ_profile[t.hour] + rng.uniform(-0.05, 0.05)))
            prov = t - timedelta(seconds=rng.randint(0, 240))
            cp_rows.append(
                [
                    cp_id,
                    str(round(lots * (1 - occ))),
                    str(lots),
                    "C",
                    _iso(prov),
                    _iso(t + timedelta(seconds=20)),
                ]
            )
        facts: dict[str, Any] = {
            "kind": "hdb_car_park" if residential else "public_car_park",
            "planning_area": code,
            "total_lots": lots,
            "car_park_type": cp_type,
            "existing_connectors": 0,
            "supply_state": "no_supply",
            "utilisation": None,
        }
        if station:
            active, inactive, lam = station
            st_id = f"SYN-ST-{len(out['stations']) + 1:02d}"
            out["stations"].append(
                {
                    "station_id": st_id,
                    "coord": xy,
                    "operator": "Sample operator",
                    "address": f"Sample address {i}",
                    "planning_area": code,
                    "provenance": "observed",
                }
            )
            out["near"].append(
                {"station_id": st_id, "site_id": site_id, "distance_m": 0.0, "threshold_m": 50}
            )
            conns = [f"{st_id}-{k}" for k in range(1, active + inactive + 1)]
            for k, cid in enumerate(conns):
                out["connectors"].append(
                    {
                        "connector_id": cid,
                        "station_id": st_id,
                        "plug_type": "Type 2",
                        "power_kw": 7.4,
                        "ever_active": k < active,
                    }
                )
            # Simulate minute by minute: arrivals at a known rate, leave if every point is busy.
            weights = res_w if residential else com_w
            busy_until = [0] * active
            arrivals = turned_away = 0
            per_snap: list[list[str]] = []
            for m in range(HOURS * 60):
                t = START + timedelta(minutes=m)
                broken = (
                    {OUT_OF_ORDER[1]}
                    if (st_id == OUT_OF_ORDER[0] and OUT_OF_ORDER[2] <= m < OUT_OF_ORDER[3])
                    else set()
                )
                if m % SNAP_EVERY == 0:
                    statuses = []
                    for k in range(active + inactive):
                        if k >= active or k in broken:
                            statuses.append("unavailable")
                        else:
                            statuses.append("occupied" if busy_until[k] > m else "available")
                    per_snap.append(statuses)
                if rng.random() < lam * weights[t.hour] / 60:
                    arrivals += 1
                    free = [k for k in range(active) if busy_until[k] <= m and k not in broken]
                    if free:
                        busy_until[free[0]] = m + rng.choices(DURATIONS, DUR_WEIGHTS)[0]
                    else:
                        turned_away += 1
            ratios, saturated, seen = [], 0, 0
            for s_idx, (t, statuses) in enumerate(zip(snaps, per_snap, strict=True)):
                if st_id == FEED_GAP[0] and s_idx in FEED_GAP[1]:
                    continue
                seen += 1
                occ_n, avail_n = statuses.count("occupied"), statuses.count("available")
                if occ_n + avail_n:
                    ratios.append(occ_n / (occ_n + avail_n))
                    saturated += avail_n == 0 and occ_n > 0
                prov = t - timedelta(seconds=rng.randint(0, 240))
                for cid, status in zip(conns, statuses, strict=True):
                    con_rows.append([cid, status, _iso(prov), _iso(t + timedelta(seconds=20))])
            util = sum(ratios) / len(ratios)
            state = "supply_idle" if util < IDLE_BELOW else "supply_active"
            facts.update(existing_connectors=active, supply_state=state, utilisation=util)
            out["indicators"].append(
                {
                    "site_id": site_id,
                    "window_start": _iso(snaps[0]),
                    "window_end": _iso(START + timedelta(hours=HOURS)),
                    "supply_state": state,
                    "active_connectors": active,
                    "utilisation": round(util, 4),
                    "saturated_fraction": round(saturated / len(ratios), 4),
                    "observation_coverage": round(seen / len(snaps), 4),
                }
            )
            bounded = util >= RELIABLE_UP_TO
            est = invert(active, RELIABLE_UP_TO if bounded else util)
            out["estimates"].append(
                {
                    "site_id": site_id,
                    "time_bin": "all",
                    "arrivals_per_hour": round(est, 4),
                    "kind": "lower_bound" if bounded else "point",
                    "note": (
                        "occupancy above the reliable limit; demand is at least this"
                        if bounded
                        else "queueing inversion of observed occupancy"
                    ),
                }
            )
            truth["sites"][site_id] = {
                "true_arrivals_per_hour": lam,
                "arrivals": arrivals,
                "turned_away": turned_away,
            }
        else:
            out["indicators"].append(
                {
                    "site_id": site_id,
                    "window_start": _iso(snaps[0]),
                    "window_end": _iso(START + timedelta(hours=HOURS)),
                    "supply_state": "no_supply",
                    "active_connectors": 0,
                    "utilisation": None,
                    "saturated_fraction": None,
                    "observation_coverage": 1.0,
                }
            )
            peak = max(occ_profile)
            scale = min(1.5, max(0.4, lots / 500))
            est = round(0.4 + 2.2 * peak * scale, 2)
            out["estimates"].append(
                {
                    "site_id": site_id,
                    "time_bin": "all",
                    "arrivals_per_hour": est,
                    "kind": "point",
                    "note": "synthetic stand-in for the no-charger regression (#16)",
                }
            )
            truth["sites"][site_id] = {
                "true_arrivals_per_hour": round(est * (1 + rng.uniform(-0.2, 0.2)), 4)
            }
        out["sites"].append(
            {
                "site_id": site_id,
                "kind": facts["kind"],
                "coord": xy,
                "planning_area": code,
                "car_park_id": cp_id,
                "total_lots": lots,
                "existing_connectors": facts["existing_connectors"],
                "provenance": "observed",
            }
        )
        site_facts[site_id] = facts

    for code, kind, amenity_lots, lam in AMENITIES:
        n_site += 1
        site_id = f"SYN-S-{n_site:02d}"
        out["sites"].append(
            {
                "site_id": site_id,
                "kind": kind,
                "coord": coord(code),
                "planning_area": code,
                "car_park_id": None,
                "total_lots": amenity_lots,
                "existing_connectors": 0,
                "provenance": "observed",
            }
        )
        out["indicators"].append(
            {
                "site_id": site_id,
                "window_start": _iso(snaps[0]),
                "window_end": _iso(START + timedelta(hours=HOURS)),
                "supply_state": "no_supply",
                "active_connectors": 0,
                "utilisation": None,
                "saturated_fraction": None,
                "observation_coverage": 1.0,
            }
        )
        out["estimates"].append(
            {
                "site_id": site_id,
                "time_bin": "all",
                "arrivals_per_hour": lam,
                "kind": "point",
                "note": "synthetic stand-in for the no-charger regression (#16)",
            }
        )
        truth["sites"][site_id] = {
            "true_arrivals_per_hour": round(lam * (1 + rng.uniform(-0.2, 0.2)), 4)
        }
        site_facts[site_id] = {
            "kind": kind,
            "planning_area": code,
            "total_lots": amenity_lots,
            "car_park_type": None,
            "existing_connectors": 0,
            "supply_state": "no_supply",
            "utilisation": None,
        }

    # Reference decisions from the five sample rules.
    for site_id, f in site_facts.items():
        results = evaluate(f)
        out["decisions"].append(
            {
                "site_id": site_id,
                "outcome": outcome(results),
                "results": results,
                "scenario_id": None,
            }
        )

    out["rules"], out["rule_on_fail"] = RULES, ON_FAIL
    out["references"] = REFERENCES
    estimates = {e["site_id"]: e["arrivals_per_hour"] for e in out["estimates"]}
    allocation, plan_scenario = allocate(out, site_facts, estimates)
    out["allocation"] = allocation
    out["infeasibility"] = over_request(out, site_facts, plan_scenario)
    top = max(allocation["items"], key=lambda it: it["marginal_relief"])
    out["scenarios"] = [
        {
            "scenario_id": sid,
            "seed": SEED,
            "growth_multiplier": g,
            "horizon_months": 51,
            "baseline_window": "2026-10-01/2026-10-03",
            "planned": (
                [
                    {
                        "site_id": top["site_id"],
                        "connectors": 2,
                        "selected_by": "planner-demo",
                        "provenance": "planned",
                    }
                ]
                if sid == plan_scenario
                else []
            ),
            "provenance": "simulated",
        }
        for sid, g in SCENARIOS
    ]
    return {
        "entities": out,
        "connector_readings": con_rows,
        "car_park_readings": cp_rows,
        "truth": truth,
    }


def evaluate(f: dict) -> list[dict]:
    lots, existing = f["total_lots"], f["existing_connectors"]
    is_car_park = f["kind"] in ("hdb_car_park", "public_car_park")
    r: list[dict] = []
    r.append(
        {
            "rule_id": "R01",
            "passed": None if lots is None else True,
            "detail": "total_lots missing" if lots is None else None,
        }
    )
    if not is_car_park:
        r.append({"rule_id": "R02", "passed": True, "detail": "not a car park"})
    else:
        r.append({"rule_id": "R02", "passed": f["car_park_type"] != BASE, "detail": None})
    if lots is None:
        r.append({"rule_id": "R03", "passed": None, "detail": "total_lots missing"})
    else:
        r.append(
            {
                "rule_id": "R03",
                "passed": existing + 1 <= MAX_SHARE * lots,
                "detail": f"room {room(lots, existing)}",
            }
        )
    r.append({"rule_id": "R04", "passed": f["supply_state"] != "supply_idle", "detail": None})
    r.append({"rule_id": "R05", "passed": f["planning_area"] is not None, "detail": None})
    return r


def room(lots: int, existing: int) -> int:
    return max(0, int(MAX_SHARE * lots) - existing)


def eligible(out: dict) -> set[str]:
    return {d["site_id"] for d in out["decisions"] if d["outcome"] in ("accept", "conditional")}


def outcome(results: list[dict]) -> str:
    failed = [ON_FAIL[x["rule_id"]] for x in results if x["passed"] is False]
    if "reject" in failed:
        return "reject"
    if any(x["passed"] is None for x in results):
        return "defer"
    return "conditional" if failed else "accept"


def allocate(out: dict, facts: dict[str, dict], est: dict[str, float]) -> tuple[dict, str]:
    """Greedy on marginal relief: meet each area's minimum first, then best step anywhere.
    Gains are concave per site, so greedy is optimal without the area minimum and close
    with it. A reference answer, not the CP-SAT optimiser."""
    scenario, growth = "base", dict(SCENARIOS)["base"]
    allowed = eligible(out)

    def space(s: str) -> int:
        return room(facts[s]["total_lots"], facts[s]["existing_connectors"])

    def gain(s: str, added: int) -> float:
        c, lam = facts[s]["existing_connectors"], est[s] * growth
        a = lam * MEAN_SESSION_H
        return lam * (erlang_b(c + added, a) - erlang_b(c + added + 1, a))

    added = {s: 0 for s in allowed}

    def best(pool: set[str]) -> str | None:
        options = [s for s in pool if added[s] < space(s)]
        return max(sorted(options), key=lambda s: gain(s, added[s])) if options else None

    while sum(added.values()) < POINTS and (s := best(allowed)) is not None:
        added[s] += 1
    items = []
    for s in sorted(added):
        if added[s]:
            relief = sum(gain(s, k) for k in range(added[s]))
            items.append(
                {
                    "site_id": s,
                    "connectors": added[s],
                    "cost": added[s] * COST_PER_POINT,
                    "marginal_relief": round(relief, 4),
                }
            )
    return (
        {
            "scenario_id": scenario,
            "planning_area": None,
            "requested_connectors": POINTS,
            "budget": None,
            "items": items,
            "checked": True,
            "violations": [],
        },
        scenario,
    )


def over_request(out: dict, facts: dict[str, dict], scenario: str) -> dict:
    """The unmet-requirement report for OVER_POINTS in OVER_AREA under OVER_BUDGET. A group
    binds when removing it alone would make the request feasible (design §4.4)."""
    in_area = [s for s in sorted(eligible(out)) if facts[s]["planning_area"] == OVER_AREA]
    caps = {
        "budget": int(OVER_BUDGET // COST_PER_POINT),
        "room": sum(room(facts[s]["total_lots"], facts[s]["existing_connectors"]) for s in in_area),
    }
    binding = [
        g
        for g in caps
        if caps[g] < OVER_POINTS and all(v >= OVER_POINTS for k, v in caps.items() if k != g)
    ]
    return {
        "scenario_id": scenario,
        "planning_area": OVER_AREA,
        "requested_connectors": OVER_POINTS,
        "max_feasible": min(OVER_POINTS, *caps.values()),
        "binding_constraints": binding,
        "affected_areas": [],
    }


def write(target: Path) -> None:
    data = build(random.Random(SEED))
    target.mkdir(parents=True, exist_ok=True)
    for name in ("entities", "truth"):
        (target / f"{name}.json").write_text(
            json.dumps(data[name], indent=1) + "\n", encoding="utf-8", newline="\n"
        )
    for name, header in (
        ("connector_readings", ["connector_id", "status", "provider_ts", "collected_ts"]),
        (
            "car_park_readings",
            [
                "car_park_id",
                "lots_available",
                "total_lots",
                "lot_type",
                "provider_ts",
                "collected_ts",
            ],
        ),
    ):
        with (target / f"{name}.csv").open("w", newline="") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(header)
            w.writerows(data[name])


if __name__ == "__main__":
    write(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "data")
    print("wrote sample data")
