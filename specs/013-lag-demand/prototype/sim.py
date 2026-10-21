"""Scratch: simulate N weekdays with the sample generator's model (arrivals by hour weight,
its session-length mix, loss when full), then score PSA vs lag-aware methods per bin."""
import random, sys
from collections import defaultdict
import numpy as np
sys.path.insert(0, sys.argv[1])
import proto as P
from optev.analysis import demand as D
from optev.sample import generate as G

def simulate(c, lam, w, days, rng, durations=G.DURATIONS, weights=G.DUR_WEIGHTS):
    busy = [0] * c
    per = defaultdict(list)
    for m in range(days * 1440):
        h = (m // 60) % 24
        if m % 30 == 0:
            per[h].append(sum(b > m for b in busy) / c)
        if rng.random() < lam * w[h] / 60:
            free = [k for k in range(c) if busy[k] <= m]
            if free:
                busy[free[0]] = m + rng.choices(durations, weights)[0]
    occ = np.array([np.mean(per[h]) for h in range(24)])
    n = np.array([len(per[h]) for h in range(24)])
    return occ, n

def smooth_psa(c, occ):
    sm = np.array([(occ[(h - 1) % 24] + 2 * occ[h] + occ[(h + 1) % 24]) / 4 for h in range(24)])
    return np.array([D.invert_occupancy(c, min(o, P.CAP)) for o in sm])

def smooth(occ):
    return np.array([(occ[(h - 1) % 24] + 2 * occ[h] + occ[(h + 1) % 24]) / 4 for h in range(24)])

def smooth_shift(c, occ, k=1):
    return shift_psa(c, smooth(occ), k)

def shift_psa(c, occ, k=1):
    """Occupancy peaks about half a session after arrivals: read bin h from bin h+k."""
    return np.array([D.invert_occupancy(c, min(occ[(h + k) % 24], P.CAP)) for h in range(24)])

def main():
    global SCALE
    days, seeds = int(sys.argv[2]), int(sys.argv[3])
    SCALE = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
    Ke, Kd = P.kernel("exp"), P.kernel("det")
    res, com = G._norm(G._RES), G._norm(G._COM)
    cases = [(2, 1.5, res), (4, 2.6, res), (8, 4.3, res), (3, 0.9, com), (6, 2.2, com), (4, 3.0, res)]
    methods = {
        "PSA (current)": lambda c, o, n: np.array([D.invert_occupancy(c, min(x, P.CAP)) for x in o]),
        "PSA smoothed": lambda c, o, n: smooth_psa(c, o),
        "PSA shifted 1h": lambda c, o, n: shift_psa(c, o, 1),
        "MOL deconv det a=1": lambda c, o, n: deconv(c, o, Kd, 1.0),
        "PSA smoothed+shift 1h": lambda c, o, n: smooth_shift(c, o, 1),
        "PSA shifted 2h": lambda c, o, n: shift_psa(c, o, 2),
        "MOL fit det a=0.1": lambda c, o, n: fit(c, o, n, Kd, 0.1),
    }
    out = defaultdict(lambda: defaultdict(list))
    for c, lam, w in cases:
        for seed in range(seeds):
            rng = random.Random(1000 * c + seed)
            occ, n = simulate(c, lam, w, days, rng, [round(d * SCALE) for d in G.DURATIONS])
            truth = np.array([lam * x for x in w])
            util = float(np.mean(occ))
            for name, fn in methods.items():
                e = fn(c, occ, n)
                out[name]["wape"].append(np.abs(e - truth).sum() / truth.sum())
                out[name]["all"].append(abs(e.mean() - lam) / lam)
                out[name]["corr"].append(np.corrcoef(e, truth)[0, 1])
                out[name]["bias"].append((e.mean() - lam) / lam)
                out[name]["util"].append(util)
    print(f"session x{SCALE}: {days} weekdays x {seeds} seeds x {len(cases)} sites")
    for name, d in out.items():
        print(f"{name:22s} per-bin WAPE {np.mean(d['wape']):.3f}  all MAPE {np.mean(d['all']):.3f}"
              f"  all bias {np.mean(d['bias']):+.3f}  profile r {np.mean(d['corr']):.2f}")

class _Ind:  # P.mol_* look up c through P.IND[s]
    def __init__(self, c): self.active_connectors = c

def deconv(c, o, K, a):
    P.IND["_"] = _Ind(c); return P.mol_deconv("_", o, K, a)

def fit(c, o, n, K, a):
    P.IND["_"] = _Ind(c); return P.mol_fit("_", o, n, K, a)

main()
