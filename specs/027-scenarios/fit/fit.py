"""Growth fit for #28 part A (spec 027): EV share of new car registrations -> fleet multipliers.

Offline, not part of the package. Reads the data.gov.sg file from data/raw/ (gitignored):

    data/raw/registrations/NewRegistrationofCarsbyMake.csv
      https://data.gov.sg/dataset/monthly-new-registration-of-cars-by-make
      (d_d3f4d708e1d0a37b4365414e2fad3a07, LTA, Jan 2016 to May 2025)

and hand-copied LTA monthly statistics (constants below). Run from SystemCode/:

    uv run python ../specs/027-scenarios/fit/fit.py

Method (spec 027 part A, as amended 22 Oct 2026):
1. Monthly share of new cars that are fully electric, s_m, for every month the file reports
   electric cars (Jul 2022 to May 2025). Fit logit(s_m) = a + b*m by least squares. A share
   cannot pass 1; a fit on the counts themselves grows past the whole COE-capped market.
2. Registrations per month = fitted share x total new cars per month (T, from LTA 2026).
3. Fleet at the collected week E_B = E0 (31 Aug 2026) + Sep 2026 registrations. Fleet at the
   horizon E_H = E_B + registrations Oct 2026 to Dec 2030 (HORIZON_MONTHS = 51). No scrappage:
   Jan to Aug 2026 the fleet grew by 99.7% of that period's registrations.
4. Multiplier = E_H / E_B. low: b at the lower 80% bound and T at the 2026 minimum month;
   high: the upper bound and the maximum month; base: the point fit and the 2026 mean.
"""

import csv
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[3]
CSV = ROOT / "data/raw/registrations/NewRegistrationofCarsbyMake.csv"

HORIZON_MONTHS = 51  # optev.assumptions.HORIZON_MONTHS: Oct 2026 to Dec 2030

# LTA M09 "Motor vehicle population by type of fuel used", cars, Electric (as at month end).
# https://www.lta.gov.sg/content/dam/ltagov/who_we_are/statistics_and_publications/statistics/pdf/M09-Vehs_by_Fuel_Type.pdf
FLEET_EV = {"2025-12": 49_110, "2026-08": 72_067}
E0 = FLEET_EV["2026-08"]

# LTA M03 "New registration of cars by make", 2026: total new cars per month (all fuels),
# and fully electric new cars over Jan-Jun and Jul-Aug (sum of the Electric rows).
# https://www.lta.gov.sg/content/dam/ltagov/who_we_are/statistics_and_publications/statistics/pdf/M03-Car_Regn_by_make.pdf
TOTAL_2026 = {"2026-01": 4266, "2026-02": 4007, "2026-03": 5049, "2026-04": 4553,
              "2026-05": 4478, "2026-06": 4791, "2026-07": 4953, "2026-08": 4549}
ELECTRIC_2026 = 16_948 + 6_080  # Jan-Jun + Jul-Aug

CI = 0.80
BACKCAST = 12


def month_index(month: str) -> int:
    """Months since Jan 2000, so differences are month counts."""
    y, m = month.split("-")
    return (int(y) - 2000) * 12 + int(m) - 1


def read_shares(path: Path) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Months with electric cars reported, their electric and total new registrations."""
    electric: Counter[str] = Counter()
    total: Counter[str] = Counter()
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            n = row["number"].strip()
            if not n:
                continue
            total[row["month"]] += int(n)
            if row["fuel_type"] == "Electric":
                electric[row["month"]] += int(n)
    months = [m for m in sorted(total) if electric[m] > 0]
    return (months, np.array([electric[m] for m in months], float),
            np.array([total[m] for m in months], float))


def fit_logit(t: np.ndarray, s: np.ndarray) -> tuple[float, float, float]:
    """Intercept, slope and the slope's standard error for logit(s) = a + b*t."""
    y = np.log(s / (1 - s))
    x = np.c_[np.ones_like(t), t]
    beta, res, *_ = np.linalg.lstsq(x, y, rcond=None)
    sigma2 = float(res[0]) / (len(t) - 2)
    se = math.sqrt(sigma2 * float(np.linalg.inv(x.T @ x)[1, 1]))
    return float(beta[0]), float(beta[1]), se


def share(a: float, b: float, t: float) -> float:
    return 1 / (1 + math.exp(-(a + b * t)))


def multiplier(a: float, b: float, monthly_total: float) -> tuple[float, float]:
    """Fleet at Dec 2030 over fleet at the collected week, and the Dec 2030 fleet."""
    sep = month_index("2026-09")
    fleet_now = E0 + share(a, b, sep) * monthly_total
    added = sum(share(a, b, sep + k) * monthly_total for k in range(1, HORIZON_MONTHS + 1))
    return (fleet_now + added) / fleet_now, fleet_now + added


def main() -> int:
    if not CSV.exists():
        print(f"Missing {CSV}; download it from data.gov.sg (see the docstring).")
        return 1
    months, ev, tot = read_shares(CSV)
    t = np.array([month_index(m) for m in months], float)
    s = ev / tot
    a, b, se = fit_logit(t, s)
    q = stats.t.ppf(0.5 + CI / 2, len(t) - 2)
    t_bar = float(t.mean())
    print(f"Fit: {months[0]} to {months[-1]}, {len(months)} months; share "
          f"{s[0]:.1%} -> {s[-1]:.1%}")
    print(f"  logit slope b = {b:.4f}/month, {CI:.0%} CI [{b - q * se:.4f}, {b + q * se:.4f}]")

    # Back-cast: fit without the last 12 months, predict their registrations.
    a12, b12, _ = fit_logit(t[:-BACKCAST], s[:-BACKCAST])
    pred = np.array([share(a12, b12, x) for x in t[-BACKCAST:]]) * tot[-BACKCAST:]
    mape = float(np.mean(np.abs(pred - ev[-BACKCAST:]) / ev[-BACKCAST:]))
    print(f"  back-cast MAPE, last {BACKCAST} months' electric registrations: {mape:.1%}")

    # Out of sample: 2026, which the fit never saw.
    pred26 = sum(share(a, b, month_index(m)) * n for m, n in TOTAL_2026.items())
    print(f"  Jan-Aug 2026 electric registrations: predicted {pred26:,.0f}, "
          f"LTA M03 {ELECTRIC_2026:,} ({pred26 / ELECTRIC_2026 - 1:+.1%})")
    grown = FLEET_EV["2026-08"] - FLEET_EV["2025-12"]
    print(f"  EV fleet grew {grown:,} over the same months (M09): "
          f"{grown / ELECTRIC_2026:.1%} of registrations, so scrappage is ignored")

    totals = list(TOTAL_2026.values())
    cases = {
        "low": (b - q * se, min(totals)),
        "base": (b, sum(totals) / len(totals)),
        "high": (b + q * se, max(totals)),
    }
    print(f"Multipliers (E0 = {E0:,} electric cars, 31 Aug 2026; {HORIZON_MONTHS} months):")
    for name, (slope, monthly) in cases.items():
        intercept = a + (b - slope) * t_bar  # pivot on the mean fitted month
        m, fleet = multiplier(intercept, slope, monthly)
        dec30 = share(intercept, slope, month_index("2030-12"))
        print(f"  {name:4s}: b={slope:.4f}, T={monthly:,.0f}/month, share Dec 2030 "
              f"{dec30:.0%}, fleet Dec 2030 {fleet:,.0f}, multiplier {m:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
