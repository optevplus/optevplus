import sys; sys.path.insert(0, sys.argv[1])
import numpy as np, proto as P
from optev.analysis import demand as D
def ss(s, o, n):
    c = P.IND[s].active_connectors
    sm = np.array([(o[(h - 1) % 24] + 2 * o[h] + o[(h + 1) % 24]) / 4 for h in range(24)])
    return np.array([D.invert_occupancy(c, min(sm[(h + 1) % 24], P.CAP)) for h in range(24)])
P.run("PSA (current)", lambda s, o, n: P.psa(s, o))
P.run("PSA smoothed+shift 1h", ss)
