"""The Allocation page (#32) on the sample: the plan, its cost, the checker's verdict, and a
plain explanation when a request cannot be met."""

from pathlib import Path

import pytest

from optev.app import data as D
from optev.app.allocation_view import BINDING, assumption_rows, infeasible, plan_rows, summary
from optev.app.shell import Request, plan
from optev.assumptions import COST_PER_POINT_SGD
from optev.contracts import Allocation, InfeasibilityReport
from optev.reasoning.checker import check

PAGE = Path(__file__).resolve().parents[1] / "optev/app/pages/3_Allocation.py"


@pytest.fixture
def sample(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(D, "ENV_FILE", tmp_path / ".env")
    return D.load()


def test_a_plan_is_summarised_with_cost_and_a_passing_check(sample):
    result, source = plan(sample, Request("base", None, 12, None))
    assert isinstance(result, Allocation) and "allocator" in source
    s = summary(check(result, sample.decisions, sample.sites))
    assert s.placed == 12 and s.requested == 12
    assert s.cost_sgd == pytest.approx(12 * COST_PER_POINT_SGD.value)
    assert s.verdict == "passed" and s.rescued_per_h > 0


def test_plan_rows_follow_the_plan_and_never_exceed_room(sample):
    result, _ = plan(sample, Request("base", None, 12, None))
    assert isinstance(result, Allocation)
    rows = plan_rows(sample, result)
    assert sum(r["new points (recommended)"] for r in rows) == 12
    assert [r["new points (recommended)"] for r in rows] == sorted(
        (r["new points (recommended)"] for r in rows), reverse=True)
    assert all(r["room left after"] >= 0 for r in rows)
    assert all(r["outcome"] in ("accept", "conditional") for r in rows)


def test_an_impossible_request_says_what_is_short(sample):
    result, _ = plan(sample, Request("base", "PR", 5000, None))
    assert isinstance(result, InfeasibilityReport)
    why = infeasible(result)
    assert why["max_feasible"] < 5000 and why["short_by"] == 5000 - why["max_feasible"]
    assert why["reasons"] and all(isinstance(r, str) for r in why["reasons"])
    assert set(why["binding"]) <= set(BINDING)


def test_every_declared_value_names_its_source():
    rows = assumption_rows()
    assert rows and all(r["source"] for r in rows)
    assert any("LTA" in r["source"] for r in rows)


def test_the_page_renders_a_plan_and_an_impossible_request(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(D, "ENV_FILE", tmp_path / ".env")
    at = AppTest.from_file(str(PAGE), default_timeout=90).run()
    assert not at.exception
    assert {m.label for m in at.metric} >= {"Points placed", "Checker"}
    assert any("found none broken" in s.value for s in at.success)
    at.sidebar.number_input(key="alloc_points").set_value(5000).run()
    assert not at.exception
    assert any("cannot be met" in e.value for e in at.error)
