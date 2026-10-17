"""SYSTEM_DESIGN.md is binding, so the code must not drift from it. These tests fail when a
table, time-bin format or declared value differs between the design and the code."""

import re
from pathlib import Path

from optev import assumptions as A
from optev.sample import generate as sample

ROOT = Path(__file__).resolve().parents[2]
DESIGN = (ROOT / "SYSTEM_DESIGN.md").read_text(encoding="utf-8")
MIGRATIONS = "\n".join(
    p.read_text(encoding="utf-8") for p in sorted((ROOT / "SystemCode/migrations").glob("*.sql"))
)


def _section(title: str) -> str:
    start = DESIGN.index(title)
    return DESIGN[start : DESIGN.index("\n### ", start + 1)]


def test_every_table_in_the_design_exists_and_no_other():
    named = set()
    for line in _section("### 3.2 Database tables").splitlines():
        if line.startswith("| `"):
            named |= set(re.findall(r"`([a-z_]+)`", line.split("|")[1]))
    # §3.2 allows ingest-internal staging tables prefixed stg_
    created = {
        t for t in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", MIGRATIONS)
        if not t.startswith("stg_")
    }
    assert named == created, f"in design only: {named - created}; in SQL only: {created - named}"


def test_time_bin_format_matches_the_design():
    assert "wd-00` … `wd-23" in DESIGN and "we-00` … `we-23" in DESIGN
    pattern = re.search(r"time_bin ~ '([^']+)'", MIGRATIONS)
    assert pattern is not None
    ok = re.compile(pattern.group(1))
    assert all(ok.match(b) for b in ("all", "wd-00", "wd-23", "we-07"))
    assert not any(ok.match(b) for b in ("wd-7", "weekday-07", "ALL"))


def test_sample_uses_the_declared_values():
    assert A.MEAN_SESSION_HOURS.value == sample.MEAN_SESSION_H
    assert A.RELIABLE_UP_TO.value == sample.RELIABLE_UP_TO
    assert A.IDLE_BELOW.value == sample.IDLE_BELOW
    assert A.COST_PER_POINT_SGD.value == sample.COST_PER_POINT
    assert A.MAX_SHARE_OF_LOTS.value == sample.MAX_SHARE
    assert A.MIN_POINTS_PER_AREA.value == sample.MIN_PER_AREA
    assert dict(sample.SCENARIOS) == {k: v.value for k, v in A.GROWTH.items()}


def test_every_assumption_states_its_unit_and_source():
    declared = [v for v in vars(A).values() if isinstance(v, A.Assumption)]
    assert declared
    assert all(a.unit and a.source for a in declared)


def test_cost_and_lot_share_are_cited_not_placeholders():
    for a in (A.COST_PER_POINT_SGD, A.COST_LOW_SGD, A.COST_HIGH_SGD, A.MAX_SHARE_OF_LOTS):
        assert "PLACEHOLDER" not in a.source and "LTA" in a.source
    assert A.COST_LOW_SGD.value <= A.COST_PER_POINT_SGD.value <= A.COST_HIGH_SGD.value


def test_allocation_and_report_ids_match_the_design_examples():
    from optev.graph.schema import allocation_key, infeasibility_key

    for example in (
        allocation_key("base", "TM", 12, None),
        allocation_key("base", None, None, 150_000.0),
        infeasibility_key("base", "PR", 40),
    ):
        assert f"`{example}`" in _section("### 3.3 Identifiers"), example


def test_every_package_in_the_design_table_exists():
    pkg = ROOT / "SystemCode/optev"
    for name in re.findall(r"^\| `([a-z_]+)/` \| §", DESIGN, flags=re.M):
        assert (pkg / name).is_dir(), name
