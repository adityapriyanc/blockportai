"""What-if scenarios for the Digital Twin (report §3 objective 5, §5.3, §7.3).

A Scenario is a declarative set of modifications applied to a COPY of the baseline state:
arrival delays, crane/capacity changes, berth outages, berth restrictions, or an explicit berth
plan. Required scenario families (objective 5):
  1. alternative berth assignment   (move a vessel to a different berth via a Plan)
  2. unexpected vessel arrival delay (shift a vessel's arrival)
  3. change in terminal capacity     (fewer cranes and/or a berth outage)
plus the Section 7 worked example (3 vessels competing for 2 berths).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

from ..models import VesselType
from .engine import FcfsPolicy, PlanPolicy, simulate
from .model import Outage, Plan, TwinBerth, TwinVessel
from .results import SimResult


@dataclass
class Scenario:
    name: str
    description: str = ""
    arrival_delays_h: Dict[int, float] = field(default_factory=dict)  # vessel id -> +hours
    berth_cranes: Dict[str, int] = field(default_factory=dict)  # berth name -> new crane count
    outages: List[Outage] = field(default_factory=list)
    allowed_berths: Dict[int, FrozenSet[str]] = field(default_factory=dict)
    plan: Optional[Plan] = None  # execute this berth plan (others fall back to FCFS)


def apply_scenario(
    vessels: Sequence[TwinVessel], berths: Sequence[TwinBerth], outages: Sequence[Outage],
    sc: Scenario,
) -> Tuple[List[TwinVessel], List[TwinBerth], List[Outage]]:
    vs = []
    for v in vessels:
        if v.id in sc.arrival_delays_h:
            v = replace(v, arrival=v.arrival + timedelta(hours=sc.arrival_delays_h[v.id]))
        if v.id in sc.allowed_berths:
            v = replace(v, allowed_berths=sc.allowed_berths[v.id])
        vs.append(v)
    bs = [replace(b, cranes=sc.berth_cranes[b.name]) if b.name in sc.berth_cranes else b
          for b in berths]
    return vs, bs, list(outages) + list(sc.outages)


def run_scenario(
    vessels: Sequence[TwinVessel], berths: Sequence[TwinBerth], sc: Scenario,
    outages: Sequence[Outage] = (),
) -> SimResult:
    vs, bs, outs = apply_scenario(vessels, berths, outages, sc)
    policy = PlanPolicy(sc.plan) if sc.plan is not None else FcfsPolicy()
    return simulate(vs, bs, outs, policy)


def compare(baseline: SimResult, results: Dict[str, SimResult]) -> List[Dict[str, object]]:
    """Tabulate scenarios against the baseline on the SAME measurement window."""
    window = baseline.window()
    base = baseline.kpis(window)
    rows = [{"scenario": "baseline", **_row(base, base)}]
    for name, res in results.items():
        rows.append({"scenario": name, **_row(res.kpis(window), base)})
    return rows


def _row(k: Dict[str, object], base: Dict[str, object]) -> Dict[str, object]:
    def pct(a: float, b: float) -> Optional[float]:
        return None if b == 0 else 100.0 * (a - b) / b
    return {
        "avg_wait_h": k["avg_wait_h"], "total_wait_h": k["total_wait_h"],
        "max_wait_h": k["max_wait_h"], "berth_utilization": k["berth_utilization"],
        "n_unserved": k["n_unserved"],
        "d_total_wait_h": k["total_wait_h"] - base["total_wait_h"],
        "d_total_wait_pct": pct(k["total_wait_h"], base["total_wait_h"]),
        "d_utilization": k["berth_utilization"] - base["berth_utilization"],
    }


# --------------------------------------------------------------------------- plan helpers
def plan_from_result(result: SimResult) -> Plan:
    """Extract the berth sequences actually used by a run (as an editable Plan)."""
    plan = Plan()
    for r in sorted(result.records, key=lambda r: r.start):
        plan.sequences.setdefault(r.berth, []).append(r.vessel_id)
    return plan


def move_vessel(plan: Plan, vessel_id: int, berth: str,
                vessels: Dict[int, TwinVessel]) -> Plan:
    """Return a copy of `plan` with the vessel moved to `berth`, inserted in arrival order."""
    new = plan.copy()
    for seq in new.sequences.values():
        if vessel_id in seq:
            seq.remove(vessel_id)
    seq = new.sequences.setdefault(berth, [])
    key = (vessels[vessel_id].arrival, vessel_id)
    pos = next((i for i, other in enumerate(seq)
                if (vessels[other].arrival, other) > key), len(seq))
    seq.insert(pos, vessel_id)
    return new


# --------------------------------------------------------------------------- standard set
def standard_scenarios(
    vessels: Sequence[TwinVessel], berths: Sequence[TwinBerth], baseline: SimResult,
    delay_h: float = 12.0, crane_factor: float = 0.5,
) -> List[Scenario]:
    """Build the three required what-if scenarios from a baseline run (deterministic choices)."""
    by_id = {v.id: v for v in vessels}
    scenarios: List[Scenario] = []

    # 1. alternative berth assignment: send the longest-waiting vessel that HAS an alternative
    #    (some types fit only one berth) to the compatible berth least used in the baseline.
    util = baseline.kpis()["per_berth_utilization"]

    def alternatives(r):
        return [b for b in berths if b.fits(by_id[r.vessel_id]) and b.name != r.berth]

    movable = [r for r in baseline.records if alternatives(r)]
    if movable:
        worst = max(movable, key=lambda r: (r.wait_h, -r.vessel_id))
        target = min(alternatives(worst), key=lambda b: (util[b.name], b.name))
        scenarios.append(Scenario(
            name="alt_berth_assignment",
            description=f"Move vessel {worst.vessel_id} from {worst.berth} to {target.name}",
            plan=move_vessel(plan_from_result(baseline), worst.vessel_id, target.name, by_id),
        ))

    # 2. unexpected arrival delay: the vessel with the median arrival time arrives late
    order = sorted(vessels, key=lambda v: (v.arrival, v.id))
    mid = order[len(order) // 2]
    scenarios.append(Scenario(
        name="arrival_delay", description=f"Vessel {mid.id} arrives {delay_h:g} h late",
        arrival_delays_h={mid.id: delay_h},
    ))

    # 3. terminal capacity change: halve the cranes at the busiest terminal
    term_util: Dict[str, float] = {}
    for b in berths:
        term_util[b.terminal] = term_util.get(b.terminal, 0.0) + util[b.name]
    terminal = max(term_util, key=lambda t: (term_util[t], t))
    scenarios.append(Scenario(
        name="capacity_change",
        description=f"Cranes at {terminal} reduced to {crane_factor:.0%}",
        berth_cranes={b.name: max(1, int(b.cranes * crane_factor))
                      for b in berths if b.terminal == terminal},
    ))
    return scenarios


# --------------------------------------------------------------------------- Section 7 case
def section7_case() -> Dict[str, object]:
    """Report §7: a delayed vessel arrives with two others; three vessels compete for the two
    berths of Terminal A while Terminal B has a free berth.

    Option A: the delayed vessel waits at anchor for a Terminal A berth.
    Option B: it is reassigned to Terminal B (trucks would be redirected; modelled in Phase 5).
    Nothing here is hard-coded: the wait times emerge from the simulation.
    """
    t = datetime(2026, 3, 3, 8, 0, tzinfo=timezone.utc)  # a Tuesday
    box = frozenset({VesselType.CONTAINER})
    berths = [TwinBerth("A1", "Terminal A", 400, 16, box),
              TwinBerth("A2", "Terminal A", 350, 15, box),
              TwinBerth("B1", "Terminal B", 330, 14.5, box)]
    only_a = frozenset({"A1", "A2"})

    def ship(i, name, cargo):
        return TwinVessel(i, name, VesselType.CONTAINER, 300, 12, cargo, t, allowed_berths=only_a)

    vessels = [ship(1, "MV Early One", 1200), ship(2, "MV Early Two", 1200),
               ship(3, "MV Delayed", 960)]
    option_b = Scenario("option_b_reassign_to_terminal_b",
                        "Delayed vessel reassigned to Terminal B",
                        allowed_berths={3: frozenset({"A1", "A2", "B1"})})
    return {"vessels": vessels, "berths": berths, "delayed_vessel_id": 3,
            "option_a": Scenario("option_a_wait_at_anchor", "Delayed vessel waits for Terminal A"),
            "option_b": option_b}


def run_section7() -> Dict[str, SimResult]:
    case = section7_case()
    return {
        "option_a": run_scenario(case["vessels"], case["berths"], case["option_a"]),
        "option_b": run_scenario(case["vessels"], case["berths"], case["option_b"]),
    }
