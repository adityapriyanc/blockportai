from datetime import datetime, timedelta, timezone

import pytest

from blockport.config import ObjectiveWeights
from blockport.db import init_db, make_engine, session_scope
from blockport.ingestion.synthetic import seed_database
from blockport.models import VesselType
from blockport.optimizer.cost_model import CostModel, ObjectiveComponents
from blockport.optimizer.optimizer import BerthOptimizer
from blockport.optimizer.reoptimize import should_reoptimize
from blockport.optimizer.sensitivity import sensitivity_analysis
from blockport.optimizer.trucks import TruckScheduler
from blockport.twin.engine import simulate
from blockport.twin.loader import berths_from_db, vessels_from_db
from blockport.twin.model import Outage, Plan, TwinBerth, TwinVessel
from blockport.twin.scenarios import section7_case

T0 = datetime(2026, 3, 3, 8, 0, tzinfo=timezone.utc)
BOX = frozenset({VesselType.CONTAINER})


def berth(
    name="A1", terminal="Terminal A", length=400, depth=16, cranes=4, types=BOX
) -> TwinBerth:
    return TwinBerth(name, terminal, length, depth, types, cranes)


def ship(
    i, arr_h=0, cargo=1200, vt=VesselType.CONTAINER, loa=300, draft=12, **kw
) -> TwinVessel:
    return TwinVessel(i, f"V{i}", vt, loa, draft, cargo, T0 + timedelta(hours=arr_h), **kw)


# ------------------------------------------------------------------ CostModel tests
def test_cost_model_evaluation():
    cm = CostModel(ObjectiveWeights(alpha=1.0, beta=0.001, gamma=0.01))
    s7 = section7_case()
    res = simulate(s7["vessels"], s7["berths"])
    obj = cm.evaluate(res)

    assert isinstance(obj, ObjectiveComponents)
    assert obj.T >= 0
    assert obj.C > 0
    assert obj.E > 0
    assert obj.J == pytest.approx(1.0 * obj.T + 0.001 * obj.C + 0.01 * obj.E)
    assert obj.truck_drayage_cost > 0
    assert obj.truck_emissions_kg > 0


# ------------------------------------------------------------------ TruckScheduler tests
def test_truck_scheduler_creates_valid_slots():
    scheduler = TruckScheduler(slot_duration_hours=2.0)
    s7 = section7_case()
    res = simulate(s7["vessels"], s7["berths"])
    slots = scheduler.schedule_from_sim(res)

    assert len(slots) > 0
    for s in slots:
        assert s.truck_count > 0
        assert s.slot_end > s.slot_start
        assert s.total_truck_miles == s.truck_count * s.miles_per_truck


# ------------------------------------------------------------------ Section 7 benchmark
def test_optimizer_solves_section7_delay_scenario():
    """Report §7: Delayed vessel reassigned to Terminal B.

    Under baseline FCFS with restriction to Terminal A, delayed vessel waits 12h at anchor.
    Optimizer assigns to free Terminal B (B1), cutting waiting time to 0!
    """
    s7 = section7_case()
    baseline_vessels = s7["vessels"]
    reassignment_candidates = [
        s7["vessels"][0],
        s7["vessels"][1],
        TwinVessel(
            3, "MV Delayed", VesselType.CONTAINER, 300, 12, 960, T0,
            allowed_berths=frozenset({"A1", "A2", "B1"}),
        ),
    ]
    berths = s7["berths"]

    opt = BerthOptimizer()
    res = opt.optimize(
        reassignment_candidates, berths, baseline_vessels=baseline_vessels
    )

    assert res.sim_result.check_invariants() == []
    # Delayed vessel assigned to Terminal B (B1)
    rec3 = res.sim_result.record_for(3)
    assert rec3.berth == "B1"
    assert rec3.wait_h == pytest.approx(0.0)

    # Total wait time is 0 vs 12h baseline
    assert res.objective.T == pytest.approx(0.0)
    assert res.baseline_objective.T == pytest.approx(12.0)
    assert res.waiting_time_reduction_pct == pytest.approx(100.0)
    assert res.met_target is True


# ------------------------------------------------------------------ Congested cluster optimization
def test_optimizer_achieves_at_least_10pct_reduction_on_congested_cluster():
    """Report §3 Objective 2: At least 10% reduction in vessel waiting time."""
    b1 = berth("A1", "Terminal A", 400, 16)
    b2 = berth("A2", "Terminal A", 350, 15)
    vessels = [
        ship(1, arr_h=0, cargo=3600),   # 32h service
        ship(2, arr_h=1, cargo=600),    # 7h service (SPT candidate)
        ship(3, arr_h=2, cargo=1200),   # 12h service
        ship(4, arr_h=3, cargo=800),    # 8.6h service
        ship(5, arr_h=4, cargo=2400),   # 22h service
    ]

    opt = BerthOptimizer(max_iterations=100)
    res = opt.optimize(vessels, [b1, b2])

    assert res.sim_result.check_invariants() == []
    assert not res.sim_result.unserved
    assert res.waiting_time_reduction_pct >= 10.0
    assert res.met_target is True
    assert res.objective.J < res.baseline_objective.J


# ------------------------------------------------------------------ Outage constraints
def test_optimizer_respects_berth_outage():
    b1 = berth("A1", "Terminal A", 400, 16)
    b2 = berth("A2", "Terminal A", 350, 15)
    outage = Outage("A1", T0 + timedelta(hours=2), T0 + timedelta(hours=20))
    vessels = [ship(1, arr_h=0, cargo=1200), ship(2, arr_h=1, cargo=1200)]

    opt = BerthOptimizer()
    res = opt.optimize(vessels, [b1, b2], outages=[outage])

    assert res.sim_result.check_invariants() == []
    for r in res.sim_result.records:
        if r.berth == "A1":
            assert not (r.start < outage.end and r.end > outage.start)


# ------------------------------------------------------------------ Re-optimization trigger
def test_should_reoptimize_triggers_on_significant_eta_shift():
    plan = Plan(sequences={"A1": [1]}, planned_start={1: T0})
    vessels = [ship(1, arr_h=0)]

    # 1. Small shift (15 min) -> no trigger
    no_trig = should_reoptimize(
        plan, vessels, updated_etas={1: T0 + timedelta(minutes=15)}, threshold_minutes=30.0
    )
    assert no_trig.triggered is False

    # 2. Large shift (45 min) -> triggers
    trig = should_reoptimize(
        plan, vessels, updated_etas={1: T0 + timedelta(minutes=45)}, threshold_minutes=30.0
    )
    assert trig.triggered is True
    assert 1 in trig.affected_vessel_ids


# ------------------------------------------------------------------ Sensitivity analysis
def test_sensitivity_analysis_generates_pareto_profiles():
    s7 = section7_case()
    points = sensitivity_analysis(s7["vessels"], s7["berths"])

    assert len(points) >= 4
    labels = [p.label for p in points]
    assert "balanced_default" in labels
    assert "time_focused" in labels
    assert "green_focused" in labels
    for p in points:
        assert isinstance(p.objective, ObjectiveComponents)


# ------------------------------------------------------------------ Database integration
def test_optimizer_runs_on_database_window(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'opt.db'}")
    init_db(engine)
    with session_scope(engine) as s:
        seed_database(s, days=20, seed=42)
    with session_scope(engine) as s:
        vessels = vessels_from_db(s)[:15]
        berths = berths_from_db(s)

    opt = BerthOptimizer(max_iterations=40)
    res = opt.optimize(vessels, berths)

    assert res.sim_result.check_invariants() == []
    assert len(res.sim_result.records) == len(vessels)
    assert res.objective.J <= res.baseline_objective.J + 1e-4
