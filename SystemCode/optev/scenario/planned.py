"""Planner selections (#29, SYSTEM_DESIGN.md §4.3).

A selection is planned capacity: it goes to `planned_capacity` under one scenario and never
into `station`, `connector` or `candidate_site` (invariant 1). Measurement does not move
because someone made a decision, so deselecting leaves the observed layer exactly as it was.

Public functions open their own connection from DATABASE_URL. The `_`-prefixed versions take
a connection, so tests can run them inside a transaction that is rolled back.
"""

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import psycopg

from optev.contracts import CandidateSite, PlannedCapacity

BASELINE = "observed"
"""The scenario id for "no scenario": planned picks on top of today's measured supply."""

_ENV = Path(__file__).resolve().parents[2] / ".env"


def _connect() -> psycopg.Connection[Any]:
    from dotenv import load_dotenv

    load_dotenv(_ENV)  # never overrides a variable already set
    return psycopg.connect(os.environ["DATABASE_URL"])


def _check_known(conn: psycopg.Connection[Any], scenario_id: str, site_id: str) -> None:
    """Refuse a typo before it becomes a silent planned row nobody can see."""
    if scenario_id != BASELINE:
        found = conn.execute(
            "SELECT 1 FROM scenario WHERE scenario_id = %s", (scenario_id,)
        ).fetchone()
        if not found:
            raise ValueError(f"unknown scenario {scenario_id!r}")
    if not conn.execute("SELECT 1 FROM candidate_site WHERE site_id = %s", (site_id,)).fetchone():
        raise ValueError(f"unknown site {site_id!r}")


def _select_site(conn: psycopg.Connection[Any], scenario_id: str, site_id: str,
                 connectors: int, selected_by: str) -> PlannedCapacity:
    pick = PlannedCapacity(site_id=site_id, connectors=connectors, selected_by=selected_by)
    _check_known(conn, scenario_id, site_id)
    # One selection per scenario and site: selecting again replaces the earlier pick.
    conn.execute(
        "DELETE FROM planned_capacity WHERE scenario_id = %s AND site_id = %s",
        (scenario_id, site_id),
    )
    conn.execute(
        "INSERT INTO planned_capacity (scenario_id, site_id, connectors, selected_by)"
        " VALUES (%s, %s, %s, %s)",
        (scenario_id, site_id, pick.connectors, pick.selected_by),
    )
    return pick


def _clear_selection(conn: psycopg.Connection[Any], scenario_id: str, site_id: str) -> int:
    cur = conn.execute(
        "DELETE FROM planned_capacity WHERE scenario_id = %s AND site_id = %s",
        (scenario_id, site_id),
    )
    return cur.rowcount


def _planned(conn: psycopg.Connection[Any], scenario_id: str) -> list[PlannedCapacity]:
    rows = conn.execute(
        "SELECT site_id, connectors, selected_by FROM planned_capacity"
        " WHERE scenario_id = %s ORDER BY site_id",
        (scenario_id,),
    ).fetchall()
    return [PlannedCapacity(site_id=s, connectors=c, selected_by=b) for s, c, b in rows]


def combine(sites: Iterable[CandidateSite],
            planned: Iterable[PlannedCapacity]) -> dict[str, int]:
    """Existing connectors plus this scenario's planned ones, per site. Pure, so the app can
    use it on the sample's `Scenario.planned` without a database."""
    extra: dict[str, int] = {}
    for pick in planned:
        extra[pick.site_id] = extra.get(pick.site_id, 0) + pick.connectors
    return {s.site_id: s.existing_connectors + extra.get(s.site_id, 0) for s in sites}


def select_site(scenario_id: str, site_id: str, connectors: int,
                selected_by: str) -> PlannedCapacity:
    """Record that a planner wants `connectors` new points at a site, in one scenario only.
    Selecting the same site again replaces the earlier pick."""
    with _connect() as conn:
        return _select_site(conn, scenario_id, site_id, connectors, selected_by)


def clear_selection(scenario_id: str, site_id: str) -> None:
    """Remove the planner's pick for a site in one scenario. Clearing nothing is fine."""
    with _connect() as conn:
        _clear_selection(conn, scenario_id, site_id)


def effective_connectors(scenario_id: str, sites: list[CandidateSite]) -> dict[str, int]:
    """What the allocator should treat as installed when solving `scenario_id`: existing
    connectors plus that scenario's planned ones. Other scenarios' picks never count."""
    with _connect() as conn:
        return combine(sites, _planned(conn, scenario_id))
