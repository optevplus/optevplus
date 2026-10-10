"""Every declared number in one place. Import from here; never hard-code a value inline.

The proposal promises that assumptions are declared and kept separate from measurement, so
each value carries its unit and where it comes from. PLACEHOLDER values must be replaced
with a cited source before the final report. Changing a value is a design change: say so in
the PR, because it moves every downstream result.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Assumption:
    value: float
    unit: str
    source: str


# Stage 2 · demand
MEAN_SESSION_HOURS = Assumption(
    3.0, "hours", "Project assumption for slow AC charging; varied +/-30% in sensitivity tests")
RELIABLE_UP_TO = Assumption(
    0.93, "share of time", "Provisional; measured by the demand recovery test (#14)")
IDLE_BELOW = Assumption(0.05, "share of time", "Project assumption: below this, supply is idle")

# Stage 3 · growth to 2030
GROWTH_LOW = Assumption(1.4, "multiplier", "PLACEHOLDER until #28 fits EV registrations")
GROWTH_BASE = Assumption(1.8, "multiplier", "PLACEHOLDER until #28 fits EV registrations")
GROWTH_HIGH = Assumption(2.2, "multiplier", "PLACEHOLDER until #28 fits EV registrations")
HORIZON_MONTHS = Assumption(51, "months", "Oct 2026 to Dec 2030")

# Stage 4 · rules and allocation
MAX_SHARE_OF_LOTS = Assumption(
    0.10, "share of car lots", "PLACEHOLDER: cap on points per site; cite LTA or HDB guidance")
COST_PER_POINT_SGD = Assumption(
    15_000.0, "SGD per charging point", "PLACEHOLDER: cite a published installed cost")
MIN_POINTS_PER_AREA = Assumption(
    2, "charging points", "Project assumption: coverage floor per planning area")

# Stage 1 · matching and collection (fixed by the proposal and Dataset Guide v2)
MATCH_THRESHOLDS_M: tuple[int, ...] = (50, 100, 200)
AMENITY_LINK_M = 150
SNAPSHOT_MINUTES = 30

GROWTH = {"low": GROWTH_LOW, "base": GROWTH_BASE, "high": GROWTH_HIGH}
