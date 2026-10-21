"""Demand at sites with no chargers (SYSTEM_DESIGN.md §4.2 step 4): with no charger there is no
occupancy to invert, so demand is learned from what a site shows without one (how full its car
park is, its size, kind and surroundings) on sites where queueing recovered a rate, then
predicted for the sites without.

Linear regression is the baseline and HistGradientBoostingRegressor the challenger; the one
with the lower leave-area-out MAE is kept. Spec 019 records what the sample can and cannot
show about either.
"""

import logging
import os
from collections import defaultdict
from datetime import datetime
from typing import Any

import numpy as np
import psycopg
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import make_pipeline

from optev.analysis.demand import _all
from optev.contracts import CandidateSite, DemandEstimate
from optev.contracts.enums import EstimateKind, SiteKind

log = logging.getLogger(__name__)

METHOD = "regression"
RANDOM_STATE = 0
# A model setting, not a declared assumption: the default leaf of 20 makes the boosted trees a
# constant on the tens of training sites we have (spec 019, question 5).
MIN_SAMPLES_LEAF = 2
NUMERIC = ["cp_occupancy_night", "cp_occupancy_day", "residents_in_area", "amenities_nearby",
           "nearest_point_m"]
LAND_USE = "land_use:"
"""Context keys: NUMERIC, plus `land_use:<VALUE>` = 1.0 for a site's land use."""


def _models() -> dict[str, Any]:
    return {
        "linear": make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True),
                                LinearRegression()),
        "hgb": HistGradientBoostingRegressor(min_samples_leaf=MIN_SAMPLES_LEAF,
                                             random_state=RANDOM_STATE),
    }


def _fit(name: str, x: np.ndarray, y: np.ndarray) -> tuple[Any, np.ndarray]:
    """The model fitted on the columns that have a value in some row: an empty column carries
    nothing, and HistGradientBoostingRegressor cannot bin one."""
    cols = ~np.isnan(x).all(axis=0)
    model = _models()[name]
    model.fit(x[:, cols], y)
    return model, cols


def _features(sites: list[CandidateSite],
              context: dict[str, dict[str, float]]) -> np.ndarray:
    """One row per site; a feature the site lacks is NaN (land use is 0 when another is set)."""
    land = sorted({k for c in context.values() for k in c if k.startswith(LAND_USE)})
    rows = []
    for s in sites:
        c = context.get(s.site_id, {})
        has_land = any(k.startswith(LAND_USE) for k in c)
        rows.append(
            [c.get(k, np.nan) for k in NUMERIC]
            + [np.nan if s.total_lots is None else float(s.total_lots)]
            + [float(s.kind == k) for k in SiteKind]
            + [c.get(k, 0.0) if has_land else np.nan for k in land])
    return np.array(rows, dtype=float)


def _leave_area_out(x: np.ndarray, y: np.ndarray, areas: list[str]) -> dict[str, float]:
    """MAE of each model, predicting every planning area from the others."""
    errors: dict[str, list[float]] = defaultdict(list)
    for area in sorted(set(areas)):
        held = np.array([a == area for a in areas])
        for name in _models():
            model, cols = _fit(name, x[~held], y[~held])
            pred = np.clip(model.predict(x[held][:, cols]), 0, None)
            errors[name] += list(np.abs(pred - y[held]))
    return {name: float(np.mean(e)) for name, e in errors.items()}


def _profiles(train: list[CandidateSite], rates: dict[str, dict[str, float]]
              ) -> dict[SiteKind | None, tuple[dict[str, float], int]]:
    """Mean normalised profile (per-bin arrivals ÷ the site's `all`) by kind, and over every
    training site under None, each rescaled so its §3.4 average is 1; with the sites used."""
    groups: dict[SiteKind | None, list[dict[str, float]]] = defaultdict(list)
    for s in train:
        r = rates[s.site_id]
        bins = {b: v / r["all"] for b, v in r.items() if b != "all"}
        if r["all"] > 0 and bins:
            groups[s.kind].append(bins)
            groups[None].append(bins)
    out = {}
    for kind, profiles in groups.items():
        mean = {b: float(np.mean([p[b] for p in profiles if b in p]))
                for b in sorted({b for p in profiles for b in p})}
        scale = _all(mean)
        out[kind] = ({b: v / scale for b, v in mean.items()} if scale > 0 else mean,
                     len(profiles))
    return out


def estimate_unserved(sites: list[CandidateSite], observed: list[DemandEstimate],
                      context: dict[str, dict[str, float]]) -> list[DemandEstimate]:
    """`all` and per-bin estimates for every site in `sites` that has none in `observed`.

    Training rows are the sites in `sites` whose `all` in `observed` is a point estimate. Pass
    the supply_active and no_supply sites, and only the supply_active sites' estimates: idle
    sites would teach the model there is no demand, and unobserved sites are left for the rules
    to defer (spec 019). Raises ValueError with training sites in fewer than two areas, since
    leave-area-out validation then has nothing to hold out."""
    rates: dict[str, dict[str, float]] = defaultdict(dict)
    point = set()
    for e in observed:
        rates[e.site_id][e.time_bin] = e.arrivals_per_hour
        if e.time_bin == "all" and e.kind == EstimateKind.POINT:
            point.add(e.site_id)
    train = [s for s in sites if s.site_id in point]
    target = [s for s in sites if s.site_id not in rates]
    if not target:
        return []
    areas = [s.planning_area or "-" for s in train]
    if len(set(areas)) < 2:
        raise ValueError(f"need training sites in at least two planning areas, got {set(areas)}")

    x, y = _features(train + target, context), np.array([rates[s.site_id]["all"] for s in train])
    mae = _leave_area_out(x[: len(train)], y, areas)
    name = min(mae, key=lambda m: (mae[m], m != "linear"))  # ties keep the baseline
    model, cols = _fit(name, x[: len(train)], y)
    predicted = np.clip(model.predict(x[len(train):, cols]), 0, None)
    log.info("estimate_unserved: kept %s (leave-area-out MAE %s) on %d sites",
             name, {m: round(v, 3) for m, v in mae.items()}, len(train))

    profiles = _profiles(train, rates)
    out: list[DemandEstimate] = []
    for s, rate in zip(target, predicted, strict=True):
        kind = s.kind if s.kind in profiles else None
        profile, n = profiles.get(kind, ({}, 0))
        note = (f"regression: {name}, {len(train)} sites, leave-area-out MAE {mae[name]:.2f}/h; "
                f"profile from {n} {kind.value if kind else 'training'} sites")
        out += [DemandEstimate(site_id=s.site_id, time_bin=b, arrivals_per_hour=float(rate) * v,
                               kind=EstimateKind.POINT, note=note) for b, v in profile.items()]
        out.append(DemandEstimate(site_id=s.site_id, time_bin="all",
                                  arrivals_per_hour=float(rate), kind=EstimateKind.POINT,
                                  note=note))
    return out


# Car park occupancy is weekday hours 00–05 (night) and 09–17 (day), SGT, over the window.
_CONTEXT_SQL = """
WITH occ AS (
    SELECT r.car_park_id,
           extract(hour FROM r.collected_ts AT TIME ZONE 'Asia/Singapore') AS h,
           1 - r.lots_available::float8 / r.total_lots AS occupancy
    FROM car_park_reading r
    WHERE r.collected_ts >= %(start)s AND r.collected_ts < %(end)s AND r.total_lots > 0
      AND r.lots_available <= r.total_lots
      AND extract(isodow FROM r.collected_ts AT TIME ZONE 'Asia/Singapore') <= 5
), cp AS (
    SELECT car_park_id,
           avg(occupancy) FILTER (WHERE h BETWEEN 0 AND 5) AS night,
           avg(occupancy) FILTER (WHERE h BETWEEN 9 AND 17) AS day
    FROM occ GROUP BY car_park_id
)
SELECT s.site_id, cp.night, cp.day, x.residents_in_area, x.amenities_nearby,
       x.nearest_point_m, x.land_use
FROM candidate_site s
LEFT JOIN cp ON cp.car_park_id = s.car_park_id
LEFT JOIN site_context x ON x.site_id = s.site_id
"""


def unserved_context(window_start: datetime, window_end: datetime
                     ) -> dict[str, dict[str, float]]:
    """site_id -> the context features of `estimate_unserved`, from `car_park_reading` over the
    window and `site_context`. A value that is missing is left out. Needs DATABASE_URL."""
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute(_CONTEXT_SQL, {"start": window_start, "end": window_end}).fetchall()
    out: dict[str, dict[str, float]] = {}
    for site, *values, land_use in rows:
        c = {k: float(v) for k, v in zip(NUMERIC, values, strict=True) if v is not None}
        if land_use:
            c[LAND_USE + land_use] = 1.0
        out[site] = c
    return out


_UPSERT_SQL = """
INSERT INTO demand_estimate (site_id, time_bin, arrivals_per_hour, kind, method, note)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (site_id, time_bin) DO UPDATE SET
    arrivals_per_hour = EXCLUDED.arrivals_per_hour, kind = EXCLUDED.kind,
    method = EXCLUDED.method, note = EXCLUDED.note
"""


def write_unserved(conn: psycopg.Connection, estimates: list[DemandEstimate]) -> int:
    """Upsert into `demand_estimate` with method 'regression', without committing."""
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_SQL, [
            (e.site_id, e.time_bin, e.arrivals_per_hour, e.kind.value, METHOD, e.note)
            for e in estimates
        ])
    log.info("write_unserved: %d rows", len(estimates))
    return len(estimates)
