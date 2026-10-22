"""Growth scenarios and projected demand (#28, SYSTEM_DESIGN.md §4.3), spec 026.

A scenario is a simulated layer on top of the observed estimates: every arrival rate is
scaled by the scenario's growth multiplier and written to `scenario_demand`, never to
`demand_estimate` (invariant 1). Rates are scaled, never occupancy: occupancy cannot pass 1,
so scaling it would hide a surge exactly at the saturated sites. A lower bound stays a lower
bound, since a multiple of a lower bound is still only a lower bound.

`make_scenarios` and `project` are pure and run on `optev.sample`. `write_scenarios` takes a
connection and does not commit, so tests can roll it back.

    uv run python -m optev.scenario.project      # read demand_estimate, project, write
"""

import logging
import os
from pathlib import Path
from typing import Any

import psycopg

from optev.assumptions import GROWTH, HORIZON_MONTHS
from optev.contracts import DemandEstimate, EstimateKind, Provenance, Scenario

log = logging.getLogger(__name__)

# The collected week the observed estimates come from (§4.1 step 1: 7 Oct 13:55 to 14 Oct
# 10:56 SGT), as `<first day>/<last day>`, the format the sample uses.
BASELINE_WINDOW = "2026-10-07/2026-10-14"

_ENV = Path(__file__).resolve().parents[2] / ".env"

_READ_ESTIMATES = """SELECT site_id, time_bin, arrivals_per_hour, kind, note
FROM demand_estimate ORDER BY site_id, time_bin"""

_UPSERT_SCENARIO = """
INSERT INTO scenario (scenario_id, seed, growth_multiplier, horizon_months, baseline_window,
                      provenance)
VALUES (%s, %s, %s, %s, %s, 'simulated')
ON CONFLICT (scenario_id) DO UPDATE SET
    seed = EXCLUDED.seed, growth_multiplier = EXCLUDED.growth_multiplier,
    horizon_months = EXCLUDED.horizon_months, baseline_window = EXCLUDED.baseline_window
"""

_CLEAR_DEMAND = "DELETE FROM scenario_demand WHERE scenario_id = %s"

_INSERT_DEMAND = """
INSERT INTO scenario_demand (scenario_id, site_id, time_bin, arrivals_per_hour, kind)
VALUES (%s, %s, %s, %s, %s)
"""


def make_scenarios() -> list[Scenario]:
    """`low`, `base` and `high`, from `GROWTH` and `HORIZON_MONTHS`."""
    return [
        Scenario(scenario_id=name, growth_multiplier=growth.value,
                 horizon_months=int(HORIZON_MONTHS.value), baseline_window=BASELINE_WINDOW,
                 provenance=Provenance.SIMULATED)
        for name, growth in GROWTH.items()
    ]


def project(estimates: list[DemandEstimate], scenario: Scenario) -> list[DemandEstimate]:
    """Every observed rate times the scenario's multiplier, keeping site, bin and kind."""
    m = scenario.growth_multiplier
    return [
        e.model_copy(update={
            "arrivals_per_hour": e.arrivals_per_hour * m,
            "note": f"simulated: x{m:g} ({scenario.scenario_id})",
        })
        for e in estimates
    ]


def write_scenarios(conn: psycopg.Connection[Any], scenarios: list[Scenario],
                    demand: dict[str, list[DemandEstimate]]) -> dict[str, int]:
    """Upsert each scenario and replace its `scenario_demand` rows, without committing.
    `demand` maps scenario id to its projected estimates. Rows written per table."""
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_SCENARIO, [
            (s.scenario_id, s.seed, s.growth_multiplier, s.horizon_months, s.baseline_window)
            for s in scenarios
        ])
        rows = 0
        for s in scenarios:
            cur.execute(_CLEAR_DEMAND, (s.scenario_id,))
            projected = demand.get(s.scenario_id, [])
            cur.executemany(_INSERT_DEMAND, [
                (s.scenario_id, e.site_id, e.time_bin, e.arrivals_per_hour, e.kind.value)
                for e in projected
            ])
            rows += len(projected)
    log.info("write_scenarios: %d scenarios, %d demand rows", len(scenarios), rows)
    return {"scenario": len(scenarios), "scenario_demand": rows}


def run(conn: psycopg.Connection[Any]) -> dict[str, int]:
    """Read the observed estimates, project them under every scenario and write them."""
    with conn.cursor() as cur:
        cur.execute(_READ_ESTIMATES)
        estimates = [
            DemandEstimate(site_id=r[0], time_bin=r[1], arrivals_per_hour=r[2],
                           kind=EstimateKind(r[3]), note=r[4])
            for r in cur.fetchall()
        ]
    scenarios = make_scenarios()
    return write_scenarios(conn, scenarios,
                           {s.scenario_id: project(estimates, s) for s in scenarios})


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(_ENV)  # never overrides a variable already set
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
        return 1
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with psycopg.connect(url) as conn:
        written = run(conn)
        conn.commit()
    for table, n in written.items():
        print(f"{table}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
