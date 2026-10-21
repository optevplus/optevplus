"""Scratch: PSA (current) vs lag-aware MOL inversions on optev.sample, scored per bin."""
import math, sys
from collections import defaultdict
from datetime import datetime, timedelta
import numpy as np
from scipy.optimize import minimize, nnls
from optev import sample
from optev.analysis import indicators as I, demand as D
from optev.sample import generate as G

S = sample.load(); R = sample.connector_readings(); T = sample.truth()["sites"]
st = datetime(2026, 10, 1, tzinfo=I.SGT); en = st + timedelta(hours=48)
IND = {i.site_id: i for i in I.compute_indicators(S.sites, S.near, S.connectors, R, st, en)}
matched = I._matched(S.near, S.connectors)
counts = I._count(matched, R, st, en)
KIND = {x.site_id: x.kind for x in S.sites}
SH = 3.0; CAP = 0.93
served = [s for s, i in IND.items() if i.supply_state in D.MEASURED]

def truth_bins(s):
    w = G._norm(G._RES if KIND[s] == "hdb_car_park" else G._COM)
    return np.array([T[s]["true_arrivals_per_hour"] * x for x in w])

def obs(s, day=None):
    """occ per hour (pooled over days, or one day), and snapshot count per hour."""
    per = defaultdict(list)
    for slot, (o, a) in counts[s].items():
        if o + a and (day is None or (slot - st).days == day):
            per[slot.hour].append(o / (o + a))
    occ = np.array([np.mean(per[h]) if per[h] else np.nan for h in range(24)])
    n = np.array([len(per[h]) for h in range(24)])
    return occ, n

def kernel(kind):
    """K[h, j]: hours of work in progress at bin h's snapshots (h:00, h:30) per unit arrival
    rate in hour j, circular over the day. Rows sum to SH."""
    surv = (lambda x: math.exp(-x / SH)) if kind == "exp" else (lambda x: 1.0 if x < SH else 0.0)
    K = np.zeros((24, 24))
    for h in range(24):
        for t in (60 * h, 60 * h + 30):
            for back in range(0, 24 * 60):          # minutes since arrival
                u = (t - back - 1) % (24 * 60)      # arrival minute
                K[h, u // 60] += surv((back + 0.5) / 60) / 60 / 2
    return K

def rho(c, m):
    return np.array([D._occupancy(c, max(x, 0.0)) for x in m])

def second_diff(n=24):
    Dm = np.zeros((n, n))
    for i in range(n):
        Dm[i, i] = -2; Dm[i, (i - 1) % n] = 1; Dm[i, (i + 1) % n] = 1
    return Dm

D2 = second_diff()

def psa(s, occ):
    c = IND[s].active_connectors
    return np.array([D.invert_occupancy(c, min(o, CAP)) for o in occ])

def mol_deconv(s, occ, K, alpha):
    c = IND[s].active_connectors
    m = np.array([D.invert_occupancy(c, min(o, CAP)) * SH for o in occ])
    A = np.vstack([K, math.sqrt(alpha) * D2]); b = np.concatenate([m, np.zeros(24)])
    return nnls(A, b)[0]

def mol_fit(s, occ, n, K, alpha, x0=None):
    c = IND[s].active_connectors
    ok = ~np.isnan(occ)
    def f(lam):
        r = rho(c, K @ lam)
        return float(np.sum(n[ok] * (occ[ok] - r[ok]) ** 2) + alpha * np.sum((D2 @ lam) ** 2))
    x0 = np.full(24, max(0.05, np.nanmean(psa(s, occ)))) if x0 is None else x0
    res = minimize(f, x0, method="L-BFGS-B", bounds=[(0, None)] * 24)
    return res.x

def score(est, s):
    t = truth_bins(s)
    return np.sum(np.abs(est - t)) / np.sum(t), (est.mean() - t.mean()) / t.mean()

def run(name, fn):
    w, a = [], []
    rows = []
    for s in served:
        occ, n = obs(s)
        e = fn(s, occ, n)
        ws, as_ = score(e, s)
        rows.append((s, ws, as_))
        if s != "SYN-S-04":
            w.append(ws); a.append(abs(as_))
    print(f"{name:34s} per-bin WAPE {np.mean(w):.3f}   all MAPE {np.mean(a):.3f}   "
          + " ".join(f"{s[-2:]}:{ws:.2f}/{as_:+.2f}" for s, ws, as_ in rows))

if __name__ == "__main__":
    Ke, Kd = kernel("exp"), kernel("det")
    run("PSA (current)", lambda s, o, n: psa(s, o))
    for al in (0.0, 0.1, 1.0, 10.0):
        run(f"MOL deconv exp a={al}", lambda s, o, n, al=al: mol_deconv(s, o, Ke, al))
    for al in (0.1, 1.0):
        run(f"MOL deconv det a={al}", lambda s, o, n, al=al: mol_deconv(s, o, Kd, al))
    for al in (0.01, 0.1, 1.0):
        run(f"MOL fit exp a={al}", lambda s, o, n, al=al: mol_fit(s, o, n, Ke, al))
    for al in (0.1,):
        run(f"MOL fit det a={al}", lambda s, o, n, al=al: mol_fit(s, o, n, Kd, al))
