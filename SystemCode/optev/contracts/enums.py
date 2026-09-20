"""Closed vocabularies shared by every package. Changing one is a breaking change."""

from enum import StrEnum


class Provenance(StrEnum):
    """Which data layer a record belongs to. The three layers are never merged."""

    OBSERVED = "observed"      # measured from a government feed
    SIMULATED = "simulated"    # generated under declared assumptions
    PLANNED = "planned"        # chosen by a planner, not yet built


class SupplyState(StrEnum):
    """Why a site's utilisation is what it is.

    The distinction that matters: NO_SUPPLY means utilisation is *undefined*, not zero.
    A ranking that treats them the same is blind to every site worth building at.
    """

    NO_SUPPLY = "no_supply"          # no connectors -> utilisation is None
    SUPPLY_IDLE = "supply_idle"      # connectors exist and are genuinely unused
    SUPPLY_ACTIVE = "supply_active"  # normal case
    UNOBSERVED = "unobserved"        # feed stale or join failed -> utilisation is None


class ConnectorStatus(StrEnum):
    """Feed status. `occupied` groups several conditions, so it is not a charging session.

    `unavailable` also covers connectors that are planned or removed, which is why a
    connector only counts toward installed capacity once seen AVAILABLE or OCCUPIED.
    """

    AVAILABLE = "available"
    OCCUPIED = "occupied"
    UNAVAILABLE = "unavailable"


class SiteKind(StrEnum):
    HDB_CAR_PARK = "hdb_car_park"
    PUBLIC_CAR_PARK = "public_car_park"
    PETROL_STATION = "petrol_station"
    HAWKER_CENTRE = "hawker_centre"
    COMMUNITY_FACILITY = "community_facility"
    EXISTING_STATION = "existing_station"


class RuleSource(StrEnum):
    """Where a rule comes from. Surfaced in explanations so a planner can weigh it."""

    GOV_DATASET = "gov_dataset"              # reads a published field
    GOV_POLICY = "gov_policy"                # cites a published document
    MATH_CONSTRAINT = "math_constraint"      # arithmetic, not a judgement
    PROJECT_ASSUMPTION = "project_assumption"  # ours, with a declared value


class Outcome(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    DEFER = "defer"            # eligible but the evidence is insufficient
    CONDITIONAL = "conditional"  # passes only if a stated fact is confirmed


class EstimateKind(StrEnum):
    POINT = "point"
    LOWER_BOUND = "lower_bound"  # site is saturated; the data supports no more than this
