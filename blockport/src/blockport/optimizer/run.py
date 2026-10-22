"""Run the multi-objective berth optimizer on a scenario window or database.

    python -m blockport.optimizer.run --db sqlite:///./blockport.db --limit 50
"""
from __future__ import annotations

import argparse
import json

from ..db import make_engine, session_scope
from ..twin.loader import berths_from_db, vessels_from_db
from ..twin.scenarios import section7_case
from .optimizer import BerthOptimizer
from .trucks import TruckScheduler


def main() -> None:
    p = argparse.ArgumentParser(description="BlockPort Multi-Objective Optimizer")
    p.add_argument("--db", default=None, help="Database connection URL")
    p.add_argument("--limit", type=int, default=40, help="Number of vessels to optimize in window")
    p.add_argument(
        "--section7", action="store_true", help="Run Section 7 vessel-delay optimization"
    )
    args = p.parse_args()

    if args.section7 or not args.db:
        s7 = section7_case()
        vessels = s7["vessels"]
        berths = s7["berths"]
        label = "Section 7 Scenario Benchmark"
    else:
        engine = make_engine(args.db)
        with session_scope(engine) as s:
            vessels = vessels_from_db(s)[: args.limit]
            berths = berths_from_db(s)
        label = f"Database Window ({len(vessels)} vessels)"

    optimizer = BerthOptimizer()
    res = optimizer.optimize(vessels, berths)

    truck_sched = TruckScheduler().schedule_from_sim(res.sim_result)

    out = {
        "scenario": label,
        "vessels_count": len(vessels),
        "iterations": res.iterations_run,
        "fcfs_baseline": {
            "total_wait_h": round(res.baseline_objective.T, 2),
            "cost_usd": round(res.baseline_objective.C, 2),
            "emissions_kg_co2": round(res.baseline_objective.E, 2),
            "score_J": round(res.baseline_objective.J, 2),
        },
        "optimized_plan": {
            "total_wait_h": round(res.objective.T, 2),
            "cost_usd": round(res.objective.C, 2),
            "emissions_kg_co2": round(res.objective.E, 2),
            "score_J": round(res.objective.J, 2),
        },
        "improvements": {
            "waiting_time_reduction_pct": round(res.waiting_time_reduction_pct, 2),
            "cost_reduction_pct": round(res.cost_reduction_pct, 2),
            "emissions_reduction_pct": round(res.emissions_reduction_pct, 2),
            "met_target_10pct": res.met_target,
        },
        "truck_assignments_count": len(truck_sched),
        "berth_sequences": res.plan.sequences,
    }

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
