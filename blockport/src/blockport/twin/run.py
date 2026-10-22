"""Run the FCFS baseline and the standard what-if scenarios on the database.

    python -m blockport.twin.run --db sqlite:///./blockport.db
"""
from __future__ import annotations

import argparse
import json

from ..db import make_engine, session_scope
from .engine import simulate
from .loader import berths_from_db, vessels_from_db
from .scenarios import compare, run_scenario, run_section7, standard_scenarios


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=None)
    args = p.parse_args()
    engine = make_engine(args.db)
    with session_scope(engine) as s:
        vessels, berths = vessels_from_db(s), berths_from_db(s)
    baseline = simulate(vessels, berths)
    assert not baseline.check_invariants()
    scenarios = standard_scenarios(vessels, berths, baseline)
    results = {sc.name: run_scenario(vessels, berths, sc) for sc in scenarios}
    s7 = run_section7()
    out = {
        "baseline_kpis": baseline.kpis(),
        "scenarios": [{"name": sc.name, "description": sc.description} for sc in scenarios],
        "comparison": compare(baseline, results),
        "section7": {k: {"wait_h_delayed_vessel": r.record_for(3).wait_h,
                         "total_wait_h": r.kpis()["total_wait_h"]} for k, r in s7.items()},
    }
    print(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
