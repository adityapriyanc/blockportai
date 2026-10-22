"""CLI reporting utility for Green Port Intelligence (report §5.5).

    python -m blockport.green.report --section7
    python -m blockport.green.report --db sqlite:///./blockport.db --limit 30
"""
from __future__ import annotations

import argparse
import json

from ..db import make_engine, session_scope
from ..optimizer.optimizer import BerthOptimizer
from ..twin.loader import berths_from_db, vessels_from_db
from ..twin.scenarios import section7_case
from .estimator import GreenPortIntelligence
from .tradeoffs import evaluate_tradeoffs


def main() -> None:
    p = argparse.ArgumentParser(description="Green Port Intelligence Audit Report")
    p.add_argument("--db", default=None, help="Database connection URL")
    p.add_argument("--limit", type=int, default=30, help="Number of vessels")
    p.add_argument("--section7", action="store_true", help="Run Section 7 Benchmark")
    p.add_argument("--shore-power", action="store_true", help="Simulate shore power / cold-ironing")
    args = p.parse_args()

    engine_green = GreenPortIntelligence(use_shore_power=args.shore_power)

    if args.section7 or not args.db:
        s7 = section7_case()
        vessels = s7["vessels"]
        berths = s7["berths"]
        label = "Section 7 Scenario Benchmark"
    else:
        db_engine = make_engine(args.db)
        with session_scope(db_engine) as s:
            vessels = vessels_from_db(s)[: args.limit]
            berths = berths_from_db(s)
        label = f"Database Window ({len(vessels)} vessels)"

    opt = BerthOptimizer()
    opt_res = opt.optimize(vessels, berths)

    base_emiss = engine_green.calculate(opt_res.fcfs_result)
    opt_emiss = engine_green.calculate(opt_res.sim_result)
    comparison = engine_green.compare_to_baseline(opt_res.fcfs_result, opt_res.sim_result)
    tradeoff = evaluate_tradeoffs(
        opt_res.fcfs_result, opt_res.sim_result, candidate_label="Optimized Schedule"
    )

    out = {
        "scenario": label,
        "cold_ironing_shore_power_active": args.shore_power,
        "baseline_fcfs": {
            "total_co2_kg": round(base_emiss.breakdown.total_co2_kg, 2),
            "anchorage_waiting_co2_kg": round(base_emiss.breakdown.anchorage_waiting_co2_kg, 2),
            "berth_hoteling_co2_kg": round(base_emiss.breakdown.berth_hoteling_co2_kg, 2),
            "crane_co2_kg": round(base_emiss.breakdown.crane_handling_co2_kg, 2),
            "truck_drayage_co2_kg": round(base_emiss.breakdown.truck_drayage_co2_kg, 2),
            "intensity_kg_co2_per_cargo_unit": round(
                base_emiss.breakdown.emissions_per_cargo_unit, 4
            ),
        },
        "optimized_plan": {
            "total_co2_kg": round(opt_emiss.breakdown.total_co2_kg, 2),
            "anchorage_waiting_co2_kg": round(opt_emiss.breakdown.anchorage_waiting_co2_kg, 2),
            "berth_hoteling_co2_kg": round(opt_emiss.breakdown.berth_hoteling_co2_kg, 2),
            "crane_co2_kg": round(opt_emiss.breakdown.crane_handling_co2_kg, 2),
            "truck_drayage_co2_kg": round(opt_emiss.breakdown.truck_drayage_co2_kg, 2),
            "intensity_kg_co2_per_cargo_unit": round(
                opt_emiss.breakdown.emissions_per_cargo_unit, 4
            ),
        },
        "comparison": {
            "reduction_intensity_pct": round(comparison.reduction_pct, 2),
            "total_co2_saved_kg": round(comparison.total_co2_saved_kg, 2),
            "met_target_5pct": comparison.met_target,
            "narrative": comparison.explanation,
        },
        "tradeoff_analysis": {
            "conflict_detected": tradeoff.conflict_detected,
            "explanation": tradeoff.explanation,
            "underlying_assumptions": tradeoff.underlying_assumptions,
        },
    }

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
