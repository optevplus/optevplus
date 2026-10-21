"""Usage patterns (SYSTEM_DESIGN.md §4.2 step 3): group sites whose occupancy rises and falls
at the same hours of the day and week.

Each site is a 48-value profile (`wd-00…wd-23`, `we-00…we-23`), min-max normalised so that
a site's shape counts, not its level. k-means picks k from 3 to 6 by silhouette. Spec 014
records how the sample clusters and why its silhouette is low.
"""

import logging
import math

import numpy as np
import psycopg
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from optev.assumptions import MIN_COVERAGE

log = logging.getLogger(__name__)

BINS = [f"{half}-{h:02d}" for half in ("wd", "we") for h in range(24)]
K_RANGE = range(3, 7)
RANDOM_STATE = 0
_N_INIT = 10
BANDS = [(0, "overnight"), (6, "morning"), (12, "daytime"), (18, "evening")]


def _profile(bins: dict[str, float]) -> np.ndarray | None:
    """The site's 48 bins, gaps filled, min-max normalised; None with too few bins seen."""
    seen = {b: v for b, v in bins.items() if b in BINS}
    if len(seen) < MIN_COVERAGE.value * len(BINS):
        return None
    overall = sum(seen.values()) / len(seen)
    half_mean = {}
    for half in ("wd", "we"):
        vals = [v for b, v in seen.items() if b.startswith(half)]
        half_mean[half] = sum(vals) / len(vals) if vals else overall
    v = np.array([seen.get(b, half_mean[b[:2]]) for b in BINS], dtype=float)
    lo, hi = v.min(), v.max()
    return (v - lo) / (hi - lo) if hi > lo else np.zeros(len(BINS))


def _profiles(occupancy: dict[str, dict[str, float]]) -> tuple[list[str], np.ndarray]:
    ids, rows = [], []
    for site in sorted(occupancy):
        p = _profile(occupancy[site])
        if p is not None:
            ids.append(site)
            rows.append(p)
    return ids, np.array(rows).reshape(len(rows), len(BINS))


def _stable(raw: np.ndarray) -> dict[int, int]:
    """Raw k-means label -> cluster numbered by first appearance in sorted site order."""
    order: dict[int, int] = {}
    for label in raw:
        order.setdefault(int(label), len(order))
    return order


def _fit(occupancy: dict[str, dict[str, float]]) -> tuple[list[str], np.ndarray, KMeans]:
    ids, x = _profiles(occupancy)
    if len(ids) < K_RANGE.start + 1:
        raise ValueError(f"need at least {K_RANGE.start + 1} sites to cluster, got {len(ids)}")
    best: tuple[float, KMeans] | None = None
    for k in K_RANGE:
        if k >= len(ids):
            break
        km = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=_N_INIT).fit(x)
        score = float(silhouette_score(x, km.labels_))
        if best is None or score > best[0]:
            best = (score, km)
    assert best is not None
    log.info("find_patterns: %d sites, k=%d, silhouette %.3f",
             len(ids), best[1].n_clusters, best[0])
    return ids, x, best[1]


def find_patterns(occupancy: dict[str, dict[str, float]]) -> dict[str, int]:
    """site_id -> cluster for every site with enough bins. Raises ValueError below 4 sites."""
    if not occupancy:
        return {}
    ids, _, km = _fit(occupancy)
    order = _stable(km.labels_)
    return {site: order[int(label)] for site, label in zip(ids, km.labels_, strict=True)}


def _label(centroid: np.ndarray) -> str:
    if not centroid.any():
        return "flat"
    wd, we = centroid[:24], centroid[24:]
    peak = int(np.argmax(wd))
    band = next(name for start, name in reversed(BANDS) if peak >= start)
    label = f"{band} peak"
    if not math.isclose(wd.mean(), we.mean()):
        label += ", busier on weekdays" if wd.mean() > we.mean() else ", busier on weekends"
    return label


def label_patterns(occupancy: dict[str, dict[str, float]],
                   patterns: dict[str, int]) -> dict[int, str]:
    """cluster -> human label, from the mean normalised profile of the cluster's sites."""
    members: dict[int, list[np.ndarray]] = {}
    for site, cluster in patterns.items():
        p = _profile(occupancy[site])
        if p is not None:
            members.setdefault(cluster, []).append(p)
    labels = {c: _label(np.mean(ps, axis=0)) for c, ps in sorted(members.items())}
    counts: dict[str, int] = {}
    for label in labels.values():
        counts[label] = counts.get(label, 0) + 1
    return {c: f"{label} (cluster {c})" if counts[label] > 1 else label
            for c, label in labels.items()}


def pattern_silhouette(occupancy: dict[str, dict[str, float]],
                       patterns: dict[str, int]) -> float:
    """Silhouette of the clustering on the normalised profiles (§6, target ≥ 0.5)."""
    ids = sorted(patterns)
    x = np.array([_profile(occupancy[s]) for s in ids])
    return float(silhouette_score(x, [patterns[s] for s in ids]))


def holdout_agreement(train: dict[str, dict[str, float]],
                      held: dict[str, dict[str, float]]) -> float:
    """Fit on `train`, assign `held` profiles to its centroids; the share of sites in both
    that keep their cluster (§6, target ≥ 0.8)."""
    ids, _, km = _fit(train)
    fitted = dict(zip(ids, km.labels_, strict=True))
    held_ids, x = _profiles({s: held[s] for s in held if s in fitted})
    if not held_ids:
        raise ValueError("no site has enough bins in both train and held")
    assigned = km.predict(x)
    kept = sum(int(a) == int(fitted[s]) for s, a in zip(held_ids, assigned, strict=True))
    return kept / len(held_ids)


_UPSERT_SQL = """
INSERT INTO site_pattern (site_id, cluster, label) VALUES (%s, %s, %s)
ON CONFLICT (site_id) DO UPDATE SET cluster = EXCLUDED.cluster, label = EXCLUDED.label
"""


def write_patterns(conn: psycopg.Connection, patterns: dict[str, int],
                   labels: dict[int, str]) -> int:
    """Upsert into `site_pattern` without committing. Returns rows written."""
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_SQL, [(site, cluster, labels.get(cluster))
                                      for site, cluster in sorted(patterns.items())])
    log.info("write_patterns: %d rows", len(patterns))
    return len(patterns)
