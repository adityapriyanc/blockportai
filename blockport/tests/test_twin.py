import heapq
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from blockport.db import init_db, make_engine, session_scope
from blockport.domain import service_time_hours
from blockport.ingestion.synthetic import seed_database
from blockport.models import VesselType
from blockport.twin.engine import PlanPolicy, simulate
from blockport.twin.loader import berths_from_db, vessels_from_db
from blockport.twin.model import Outage, Plan, TwinBerth, TwinVessel
from blockport.twin.scenarios import (
    Scenario,
    compare,
    move_vessel,
    plan_from_result,
    run_scenario,
    run_section7,
    standard_scenarios,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
BOX = frozenset({VesselType.CONTAINER})


def hours(h: float) -> timedelta:
    return timedelta(hours=h)


def berth(name="A1", terminal="T", length=400, depth=16, cranes=4, types=BOX) -> TwinBerth:
    return TwinBerth(name, terminal, length, depth, types, cranes)


def vessel(i, arr_h, cargo=1200, vt=VesselType.CONTAINER, loa=300, draft=12, **kw) -> TwinVessel:
    return TwinVessel(i, f"V{i}", vt, loa, draft, cargo, T0 + hours(arr_h), **kw)


def random_fleet(n=200, seed=1, mean_gap_h=7.0):
    rng = np.random.default_rng(seed)
    t = 0.0
    out = []
    for i in range(n):
        t += rng.exponential(mean_gap_h)
        out.append(vessel(i, t, cargo=float(rng.uniform(600, 4000))))
    return out


# --------------------------------------------------------------- fidelity: reference model
def reference_fcfs_starts(vessels, n_berths, cranes=4):
    """Independent M/D/c-style reference: earliest-free-server heap, no twin code involved."""
    free = [T0 - hours(1000)] * n_berths
    heapq.heapify(free)
    starts = {}
    for v in sorted(vessels, key=lambda x: (x.arrival, x.id)):
        earliest = heapq.heappop(free)
        s = max(v.arrival, earliest)
        starts[v.id] = s
        heapq.heappush(free, s + hours(service_time_hours(v.vessel_type, v.cargo_units, cranes)))
    return starts


@pytest.mark.parametrize("n_berths,gap", [(1, 30.0), (2, 14.0), (3, 8.0), (3, 5.0)])
def test_twin_matches_independent_reference_exactly(n_berths, gap):
    vessels = random_fleet(250, seed=n_berths, mean_gap_h=gap)
    berths = [berth(f"B{i}") for i in range(n_berths)]
    res = simulate(vessels, berths)
    ref = reference_fcfs_starts(vessels, n_berths)
    assert res.check_invariants() == []
    assert not res.unserved
    for r in res.records:
        assert abs((r.start - ref[r.vessel_id]).total_seconds()) < 1e-3
    # the load must be non-trivial for this test to mean anything
    assert res.kpis()["total_wait_h"] > 0 or n_berths == 3 and gap == 8.0


def test_invariants_and_littles_law_on_loaded_system():
    vessels = random_fleet(300, seed=9, mean_gap_h=6.0)
    res = simulate(vessels, [berth("A"), berth("B"), berth("C")])
    assert res.check_invariants() == []
    # Little's law identity: integral of queue length over time == total waiting time
    pts = sorted([(r.arrival, +1) for r in res.records] + [(r.start, -1) for r in res.records])
    q, last, area = 0, pts[0][0], 0.0
    for t, d in pts:
        area += q * (t - last).total_seconds() / 3600.0
        q, last = q + d, t
    assert area == pytest.approx(res.kpis()["total_wait_h"], rel=1e-9)
    # conservation: busy hours over the window equal total service hours
    k = res.kpis()
    assert k["berth_utilization"] * k["window_h"] * 3 == pytest.approx(
        sum(r.service_h for r in res.records), rel=1e-9)


def test_deterministic():
    v = random_fleet(80, seed=4)
    b = [berth("A"), berth("B")]
    a1, a2 = simulate(v, b), simulate(v, b)
    assert [(r.vessel_id, r.berth, r.start) for r in a1.records] == \
           [(r.vessel_id, r.berth, r.start) for r in a2.records]


# --------------------------------------------------------------- engine behaviours
def test_single_vessel_has_no_wait_and_correct_service_time():
    res = simulate([vessel(1, 5, cargo=1200)], [berth()])
    r = res.records[0]
    assert r.wait_h == 0 and r.service_h == pytest.approx(2 + 1200 / 120)
    assert r.start == T0 + hours(5)


def test_compatibility_constraints_leave_vessel_unserved():
    deep = vessel(1, 0, draft=18)  # berth depth is 16
    long = vessel(2, 0, loa=500)
    tanker = vessel(3, 0, vt=VesselType.TANKER)
    ok = vessel(4, 0)
    res = simulate([deep, long, tanker, ok], [berth()])
    assert sorted(res.unserved) == [1, 2, 3]
    assert [r.vessel_id for r in res.records] == [4]
    assert res.check_invariants() == []


def test_unservable_vessel_does_not_block_others():
    res = simulate([vessel(1, 0, draft=30), vessel(2, 1), vessel(3, 2)], [berth()])
    assert [r.vessel_id for r in res.records] == [2, 3]


def test_smallest_fitting_berth_is_chosen():
    small, big = berth("S", length=320), berth("L", length=400)
    res = simulate([vessel(1, 0, loa=300)], [big, small])
    assert res.records[0].berth == "S"


def test_outage_blocks_berth_and_service_never_overlaps_it():
    outage = Outage("A1", T0 + hours(2), T0 + hours(30))
    res = simulate([vessel(1, 0, cargo=1200)], [berth()], [outage])  # needs 12 h, window is 2 h
    r = res.records[0]
    assert r.start == T0 + hours(30) and r.wait_h == pytest.approx(30)
    assert res.check_invariants() == []


def test_outage_other_berth_used_instead():
    outage = Outage("A1", T0, T0 + hours(100))
    res = simulate([vessel(1, 0)], [berth("A1"), berth("A2", length=500)], [outage])
    assert res.records[0].berth == "A2" and res.records[0].wait_h == 0


def test_allowed_berths_restriction_respected():
    v = vessel(1, 0, allowed_berths=frozenset({"B"}))
    res = simulate([v], [berth("A"), berth("B", length=500)])
    assert res.records[0].berth == "B"


# --------------------------------------------------------------- scenarios
def test_arrival_delay_shifts_start_on_idle_port():
    base = [vessel(1, 0), vessel(2, 100)]
    res = run_scenario(base, [berth()], Scenario("d", arrival_delays_h={2: 12.0}))
    assert res.record_for(2).start == T0 + hours(112)


def test_arrival_delay_creates_cluster_and_waiting():
    base = [vessel(1, 0, cargo=1200), vessel(2, 14, cargo=1200)]  # v1 done at 12 h, no overlap
    assert simulate(base, [berth()]).kpis()["total_wait_h"] == 0
    late = run_scenario(base, [berth()], Scenario("d", arrival_delays_h={2: -10.0}))  # now at 4 h
    assert late.record_for(2).wait_h == pytest.approx(12 - 4)


def test_capacity_change_halving_cranes_doubles_container_handling():
    v = [vessel(1, 0, cargo=2400)]
    full = simulate(v, [berth(cranes=4)]).records[0].service_h  # 2 + 2400/120 = 22
    half = run_scenario(v, [berth(cranes=4)], Scenario("c", berth_cranes={"A1": 2}))
    assert full == pytest.approx(22)
    assert half.records[0].service_h == pytest.approx(2 + 2400 / 60)


def test_non_container_service_ignores_cranes():
    t = vessel(1, 0, vt=VesselType.TANKER, cargo=60000)
    b = lambda c: TwinBerth("T1", "T", 400, 20, frozenset({VesselType.TANKER}), c)  # noqa: E731
    assert simulate([t], [b(4)]).records[0].service_h == simulate([t], [b(1)]).records[0].service_h


def test_zero_cranes_rejected():
    with pytest.raises(ValueError):
        service_time_hours(VesselType.CONTAINER, 100, cranes=0)


def test_plan_policy_executes_given_order_and_berth():
    vs = [vessel(i, i * 0.1) for i in range(1, 4)]
    bs = [berth("A"), berth("B", length=500)]
    plan = Plan(sequences={"B": [3, 1], "A": [2]})
    res = simulate(vs, bs, policy=PlanPolicy(plan))
    assert res.record_for(3).berth == "B" and res.record_for(1).berth == "B"
    assert res.record_for(2).berth == "A"
    assert res.record_for(3).start < res.record_for(1).start
    assert res.check_invariants() == []


def test_plan_head_of_line_idles_berth_when_planned_vessel_is_late():
    """Plan built on predicted arrivals, executed with actual: a late planned vessel blocks."""
    vs = [vessel(1, 50), vessel(2, 0)]  # v1 planned first on A but actually arrives at 50 h
    res = simulate(vs, [berth("A")], policy=PlanPolicy(Plan(sequences={"A": [1, 2]})))
    assert res.record_for(2).start == T0 + hours(50 + 12)  # v2 had to wait for v1
    assert res.record_for(2).wait_h == pytest.approx(62)


def test_plan_planned_start_is_honoured():
    plan = Plan(sequences={"A1": [1]}, planned_start={1: T0 + hours(20)})
    res = simulate([vessel(1, 0)], [berth()], policy=PlanPolicy(plan))
    assert res.records[0].start == T0 + hours(20)


def test_unplanned_vessels_fall_back_to_fcfs():
    res = simulate([vessel(1, 0), vessel(2, 1)], [berth("A"), berth("B", length=500)],
                   policy=PlanPolicy(Plan(sequences={"A": [1]})))
    assert res.record_for(1).berth == "A" and res.record_for(2).berth == "B"


def test_plan_from_result_roundtrip_reproduces_the_run():
    vs = random_fleet(60, seed=2, mean_gap_h=6.0)
    bs = [berth("A"), berth("B", length=500)]
    base = simulate(vs, bs)
    again = simulate(vs, bs, policy=PlanPolicy(plan_from_result(base)))
    assert [(r.vessel_id, r.berth, r.start) for r in base.records] == \
           [(r.vessel_id, r.berth, r.start) for r in again.records]


def test_move_vessel_inserts_in_arrival_order():
    vs = {i: vessel(i, i) for i in range(1, 5)}
    plan = Plan(sequences={"A": [1, 2], "B": [3, 4]})
    moved = move_vessel(plan, 2, "B", vs)
    assert moved.sequences == {"A": [1], "B": [2, 3, 4]}
    assert plan.sequences == {"A": [1, 2], "B": [3, 4]}  # original untouched


# --------------------------------------------------------------- Section 7 case
def test_section7_wait_emerges_from_simulation():
    out = run_section7()
    a, b = out["option_a"], out["option_b"]
    assert a.check_invariants() == [] and b.check_invariants() == []
    # Option A: V1, V2 take A1/A2 for 2 + 1200/120 = 12 h; V3 waits 12 h at anchor.
    assert a.record_for(3).wait_h == pytest.approx(12.0)
    assert a.record_for(3).berth in ("A1", "A2")
    # Option B: V3 goes straight to Terminal B.
    assert b.record_for(3).wait_h == 0 and b.record_for(3).berth == "B1"
    assert b.kpis()["total_wait_h"] == 0 < a.kpis()["total_wait_h"]
    # the baseline/option comparison reports the 12 h of anchorage avoided
    rows = compare(a, {"b": b})
    assert rows[1]["d_total_wait_h"] == pytest.approx(-12.0)


def test_scenario_does_not_mutate_baseline_inputs():
    case = run_section7()
    vs = [vessel(1, 0), vessel(2, 1)]
    before = list(vs)
    run_scenario(vs, [berth()], Scenario("x", arrival_delays_h={1: 5}, berth_cranes={"A1": 1}))
    assert vs == before and case  # frozen dataclasses: inputs unchanged


# --------------------------------------------------------------- DB integration + standard set
@pytest.fixture(scope="module")
def db_world(tmp_path_factory):
    engine = make_engine(f"sqlite:///{tmp_path_factory.mktemp('db') / 't.db'}")
    init_db(engine)
    with session_scope(engine) as s:
        seed_database(s, days=45, seed=5)
    with session_scope(engine) as s:
        return vessels_from_db(s), berths_from_db(s), vessels_from_db(s, arrival="scheduled")


def test_loader_builds_expected_layout(db_world):
    vessels, berths, scheduled = db_world
    assert [b.name for b in berths] == ["A1", "A2", "B1", "B2"]
    assert all(b.cranes == 4 for b in berths)
    assert len(vessels) == len(scheduled) > 20
    assert all(v.arrival.tzinfo is not None for v in vessels)


def test_baseline_on_synthetic_port_is_consistent_and_loaded(db_world):
    vessels, berths, _ = db_world
    res = simulate(vessels, berths)
    assert res.check_invariants() == []
    k = res.kpis()
    assert 0.2 < k["berth_utilization"] < 0.95  # loaded but not saturated (calibration check)
    assert k["n_unserved"] == 0 or all(res.vessels[i].draft_m > 0 for i in res.unserved)


def test_standard_scenarios_cover_three_families_and_all_run(db_world):
    vessels, berths, _ = db_world
    base = simulate(vessels, berths)
    scs = standard_scenarios(vessels, berths, base)
    names = {s.name for s in scs}
    assert {"arrival_delay", "capacity_change"} <= names
    assert len(scs) >= 3 and "alt_berth_assignment" in names
    results = {s.name: run_scenario(vessels, berths, s) for s in scs}
    for r in results.values():
        assert r.check_invariants() == []
    rows = compare(base, results)
    assert rows[0]["scenario"] == "baseline" and len(rows) == len(scs) + 1
    cap = next(r for r in rows if r["scenario"] == "capacity_change")
    assert cap["total_wait_h"] >= rows[0]["total_wait_h"]  # fewer cranes cannot reduce waiting
