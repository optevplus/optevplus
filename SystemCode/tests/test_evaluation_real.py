"""Real-data comparison (#39) and Stage 3 stability, without a database."""

from typing import Any

from optev.evaluation import harness as H
from optev.evaluation import stability as St
from optev.evaluation.real import methods, real_inputs

REQ, INPUTS, METHODS = H.sample_inputs()


def test_the_best_baseline_is_the_best_of_all_baselines_not_only_random():
    rows = H.compare(REQ, INPUTS, METHODS)
    baselines = [r for r in rows if not r.method.startswith(H.NOT_BASELINES)]
    assert len(baselines) >= 4  # random, population share, busiest first, spatial spread
    best = max(baselines, key=lambda r: r.rescued)
    assert abs(best.vs_best_baseline - 1.0) < 1e-9
    assert all(r.vs_best_baseline <= 1.0 + 1e-9 for r in baselines)


def test_real_inputs_are_built_from_the_pipelines_tables():
    rows: dict[str, list[dict[str, Any]]] = {
        "decisions": [{"site_id": s.site_id, "scenario_id": "observed",
                       "outcome": d.outcome.value}
                      for s, d in zip(INPUTS.sites, INPUTS.decisions, strict=False)],
        "results": [], "planned": [], "sites": [],
        "scenarios": [{"scenario_id": "base", "seed": 0, "growth_multiplier": 1.8,
                       "horizon_months": 51, "baseline_window": None,
                       "provenance": "simulated"}],
        "scenario_demand": [{"site_id": "SYN-S-01", "time_bin": "all",
                             "arrivals_per_hour": 2.0, "kind": "point"}],
        "indicators": [i.model_dump(mode="json") for i in INPUTS.indicators],
        "residents": [{"planning_area": "TM", "residents": 270000}],
    }
    inputs = real_inputs(lambda name, *p: rows[name], "base")
    assert inputs.scenario.scenario_id == "base" and inputs.demand[0].arrivals_per_hour == 2.0
    assert inputs.residents == {"TM": 270000} and len(inputs.indicators) == len(INPUTS.indicators)


def test_the_optimiser_and_every_registered_baseline_take_part():
    found = methods()
    assert "optimiser (CP-SAT)" in found
    assert {"busiest first (#36)", "spatial spread (#37)"} <= set(found)


def test_stability_reports_kept_top_sites_for_each_perturbation():
    results = St.stability(INPUTS, H.Request("base", 12, None))
    labels = [r.perturbation for r in results]
    assert labels[:2] == ["growth -20%", "growth +20%"] and len(results) == 2 + St.SEEDS
    assert all(0 <= r.kept <= r.of for r in results)
    assert results[0].kept == results[0].of  # scaling every rate alike keeps the ranking
    assert "Meets" in St.markdown(results)
