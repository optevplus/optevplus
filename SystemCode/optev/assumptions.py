"""Every declared number in one place. Import from here; never hard-code a value inline.

The proposal promises that assumptions are declared and kept separate from measurement, so
each value carries its unit and where it comes from; SYSTEM_DESIGN.md §3.5 links the cited
sources. PLACEHOLDER values must be replaced with a cited source before the final report.
Changing a value is a design change: say so in the PR, because it moves every downstream
result.
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
MIN_COVERAGE = Assumption(
    0.5, "share of expected snapshots",
    "Project assumption: below this, a site's utilisation is unobserved, not measured")

# Stage 3 · growth to 2030
GROWTH_LOW = Assumption(1.4, "multiplier", "PLACEHOLDER until #28 fits EV registrations")
GROWTH_BASE = Assumption(1.8, "multiplier", "PLACEHOLDER until #28 fits EV registrations")
GROWTH_HIGH = Assumption(2.2, "multiplier", "PLACEHOLDER until #28 fits EV registrations")
HORIZON_MONTHS = Assumption(51, "months", "Oct 2026 to Dec 2030")

# Stage 4 · rules and allocation
MAX_SHARE_OF_LOTS = Assumption(
    0.15, "share of car lots",
    "LTA factsheet, 4 Mar 2021: new HDB car parks have electrical capacity for slow charging "
    "at 15% of lots. Used as the upper limit per site; existing car parks may have less")
# A charger in the ECCG examples is one slow AC unit; we count it as one charging point.
# Only used when the planner gives a budget; the number of points needs no cost at all.
COST_PER_POINT_SGD = Assumption(
    9_250.0, "SGD per charging point",
    "LTA ECCG Guidelines and FAQs, 5 Mar 2025, example 3: equipment, electrician fees and "
    "cabling averaged per charger")
COST_LOW_SGD = Assumption(
    5_500.0, "SGD per charging point", "LTA ECCG Guidelines and FAQs, example 1 (low end)")
COST_HIGH_SGD = Assumption(
    10_500.0, "SGD per charging point", "LTA ECCG Guidelines and FAQs, example 2 (high end)")

# Stage 1 · matching and collection (fixed by the proposal and Dataset Guide v2)
MATCH_THRESHOLDS_M: tuple[int, ...] = (50, 100, 200)
AMENITY_LINK_M = 150
SNAPSHOT_MINUTES = 30

GROWTH = {"low": GROWTH_LOW, "base": GROWTH_BASE, "high": GROWTH_HIGH}
