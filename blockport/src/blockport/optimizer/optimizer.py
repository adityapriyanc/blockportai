"""Multi-objective Berth Allocation and Scheduling Optimizer (report §5.4).

Solves the constrained multi-objective problem:
    Minimize J = alpha * T + beta * C + gamma * E

Subject to:
    1. Vessel-berth dimensional & type compatibility: length <= berth.length, draft <= berth.depth.
    2. Operational berth availability & outage non-overlap: no service during outage intervals.
    3. Temporal arrival feasibility: service_start >= arrival.
    4. Non-overlapping berth occupation: no two vessels occupy the same berth simultaneously.
    5. Specific berth restrictions: allowed_berths respected if specified.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from ..config import ObjectiveWeights, get_settings
from ..twin.engine import FcfsPolicy, PlanPolicy, simulate
from ..twin.model import Outage, Plan, TwinBerth, TwinVessel
from ..twin.results import SimResult
from .cost_model import CostModel, ObjectiveComponents


@dataclass
class OptimizationResult:
    plan: Plan
    sim_result: SimResult
    fcfs_result: SimResult
    objective: ObjectiveComponents
    baseline_objective: ObjectiveComponents
    waiting_time_reduction_pct: float
    emissions_reduction_pct: float
    cost_reduction_pct: float
    met_target: bool
    iterations_run: int


class BerthOptimizer:
    def __init__(
        self,
        weights: Optional[ObjectiveWeights] = None,
        cost_model: Optional[CostModel] = None,
        max_iterations: int = 150,
    ):
        self.weights = weights or get_settings().objective_weights
        self.cost_model = cost_model or CostModel(weights=self.weights)
        self.max_iterations = max_iterations

    def _is_slot_free_of_outages(
        self, berth_name: str, start: datetime, end: datetime, outages: Sequence[Outage]
    ) -> bool:
        return not any(
            o.berth == berth_name and o.start < end and o.end > start
            for o in outages
        )

    def _build_schedule_for_sequences(
        self,
        sequences: Dict[str, List[int]],
        vessels_by_id: Dict[int, TwinVessel],
        berths_by_name: Dict[str, TwinBerth],
        outages: Sequence[Outage],
    ) -> Tuple[bool, Dict[int, datetime]]:
        """Compute earliest feasible start times for each vessel in the berth sequences."""
        planned_starts: Dict[int, datetime] = {}

        for berth_name, seq in sequences.items():
            berth = berths_by_name[berth_name]
            current_time = datetime.min

            for vid in seq:
                v = vessels_by_id[vid]
                if not berth.fits(v):
                    return False, {}
                if v.allowed_berths is not None and berth.name not in v.allowed_berths:
                    return False, {}

                svc_h = berth.service_hours(v)
                svc_duration = timedelta(hours=svc_h)

                # Earliest candidate start is max(vessel arrival, previous vessel departure)
                cand_start = (
                    v.arrival if current_time == datetime.min else max(v.arrival, current_time)
                )

                # Advance past any overlapping outages
                attempts = 0
                while not self._is_slot_free_of_outages(
                    berth_name, cand_start, cand_start + svc_duration, outages
                ):
                    overlapping = [
                        o for o in outages
                        if o.berth == berth_name
                        and o.start < cand_start + svc_duration
                        and o.end > cand_start
                    ]
                    if not overlapping:
                        break
                    cand_start = max(o.end for o in overlapping)
                    attempts += 1
                    if attempts > len(outages) + 2:
                        return False, {}

                planned_starts[vid] = cand_start
                current_time = cand_start + svc_duration

        return True, planned_starts

    def optimize(
        self,
        vessels: Sequence[TwinVessel],
        berths: Sequence[TwinBerth],
        outages: Sequence[Outage] = (),
        baseline_vessels: Optional[Sequence[TwinVessel]] = None,
    ) -> OptimizationResult:
        """Run multi-objective optimization to generate the best operational plan."""
        vessels_by_id = {v.id: v for v in vessels}
        berths_by_name = {b.name: b for b in berths}

        # 1. Baseline: Run standard FCFS on baseline_vessels or vessels
        base_vs = baseline_vessels or vessels
        fcfs_result = simulate(base_vs, berths, outages, policy=FcfsPolicy())
        base_obj = self.cost_model.evaluate(fcfs_result)

        # 2. Construct initial candidate plans
        candidates: List[Dict[str, List[int]]] = []

        # Candidate A: FCFS order derived plan
        fcfs_seqs: Dict[str, List[int]] = {b.name: [] for b in berths}
        for r in sorted(fcfs_result.records, key=lambda x: x.start):
            if r.vessel_id in vessels_by_id:
                fcfs_seqs[r.berth].append(r.vessel_id)
        candidates.append(fcfs_seqs)

        # Candidate B: Greedy minimum-completion-time insertion
        greedy_seqs: Dict[str, List[int]] = {b.name: [] for b in berths}
        sorted_vessels = sorted(vessels, key=lambda v: (v.arrival, v.id))
        for v in sorted_vessels:
            best_b = None
            best_completion = None
            for b in berths:
                if not b.fits(v):
                    continue
                if v.allowed_berths is not None and b.name not in v.allowed_berths:
                    continue
                trial_seqs = {k: list(sublist) for k, sublist in greedy_seqs.items()}
                trial_seqs[b.name].append(v.id)
                feasible, starts = self._build_schedule_for_sequences(
                    trial_seqs, vessels_by_id, berths_by_name, outages
                )
                if feasible and v.id in starts:
                    comp = starts[v.id] + timedelta(hours=b.service_hours(v))
                    if best_completion is None or comp < best_completion:
                        best_completion = comp
                        best_b = b.name
            if best_b:
                greedy_seqs[best_b].append(v.id)
        candidates.append(greedy_seqs)

        # Candidate C: Shortest Processing Time (SPT) first for close arrivals (< 6 hours)
        spt_seqs: Dict[str, List[int]] = {b.name: [] for b in berths}
        clustered_vessels = list(sorted_vessels)
        i = 0
        while i < len(clustered_vessels):
            j = i + 1
            while j < len(clustered_vessels):
                dt = (clustered_vessels[j].arrival - clustered_vessels[i].arrival).total_seconds()
                if dt > 21600:
                    break
                j += 1
            clustered_vessels[i:j] = sorted(
                clustered_vessels[i:j],
                key=lambda v: (min(b.service_hours(v) for b in berths if b.fits(v)), v.arrival)
            )
            i = j

        for v in clustered_vessels:
            compat_berths = [
                b for b in berths
                if b.fits(v) and (v.allowed_berths is None or b.name in v.allowed_berths)
            ]
            if compat_berths:
                best_b = min(
                    compat_berths,
                    key=lambda b: (len(spt_seqs[b.name]), b.service_hours(v), b.name),
                )
                spt_seqs[best_b.name].append(v.id)
        candidates.append(spt_seqs)

        # Evaluate candidate plans and pick best initial
        best_plan: Optional[Plan] = None
        best_sim: Optional[SimResult] = None
        best_obj: Optional[ObjectiveComponents] = None
        best_score = float("inf")

        for seqs in candidates:
            feasible, starts = self._build_schedule_for_sequences(
                seqs, vessels_by_id, berths_by_name, outages
            )
            if not feasible:
                continue
            plan = Plan(sequences=seqs, planned_start=starts)
            sim_res = simulate(vessels, berths, outages, policy=PlanPolicy(plan))
            if not sim_res.check_invariants() and not sim_res.unserved:
                obj = self.cost_model.evaluate(sim_res)
                if obj.J < best_score:
                    best_score = obj.J
                    best_plan = plan
                    best_sim = sim_res
                    best_obj = obj

        if best_plan is None:
            best_plan = Plan(sequences=fcfs_seqs)
            best_sim = fcfs_result
            best_obj = base_obj
            best_score = base_obj.J

        # 3. Neighborhood Search Improvement
        current_seqs = {k: list(sublist) for k, sublist in best_plan.sequences.items()}
        iterations = 0

        for _ in range(self.max_iterations):
            iterations += 1
            improved = False

            # Move type 1: Relocate a vessel to another compatible berth
            for b_source, v_list in list(current_seqs.items()):
                if not v_list:
                    continue
                for idx, vid in enumerate(v_list):
                    v = vessels_by_id[vid]
                    for b_dest in berths:
                        if b_dest.name == b_source or not b_dest.fits(v):
                            continue
                        if v.allowed_berths is not None and b_dest.name not in v.allowed_berths:
                            continue

                        trial_seqs = {k: list(sublist) for k, sublist in current_seqs.items()}
                        trial_seqs[b_source].pop(idx)

                        dest_list = trial_seqs[b_dest.name]
                        ins_pos = 0
                        while (
                            ins_pos < len(dest_list)
                            and vessels_by_id[dest_list[ins_pos]].arrival <= v.arrival
                        ):
                            ins_pos += 1
                        dest_list.insert(ins_pos, vid)

                        feasible, starts = self._build_schedule_for_sequences(
                            trial_seqs, vessels_by_id, berths_by_name, outages
                        )
                        if not feasible:
                            continue

                        trial_plan = Plan(sequences=trial_seqs, planned_start=starts)
                        sim_res = simulate(vessels, berths, outages, policy=PlanPolicy(trial_plan))
                        if not sim_res.check_invariants() and not sim_res.unserved:
                            obj = self.cost_model.evaluate(sim_res)
                            if obj.J < best_score - 1e-4:
                                best_score = obj.J
                                current_seqs = trial_seqs
                                best_plan = trial_plan
                                best_sim = sim_res
                                best_obj = obj
                                improved = True
                                break
                    if improved:
                        break
                if improved:
                    break

            if not improved:
                # Move type 2: Swap adjacent vessels in congested berth sequences
                for b_name, v_list in list(current_seqs.items()):
                    if len(v_list) < 2:
                        continue
                    for idx in range(len(v_list) - 1):
                        v1, v2 = v_list[idx], v_list[idx + 1]
                        dt_swap = abs(
                            (vessels_by_id[v1].arrival - vessels_by_id[v2].arrival).total_seconds()
                        )
                        if dt_swap <= 14400:
                            trial_seqs = {k: list(sublist) for k, sublist in current_seqs.items()}
                            trial_seqs[b_name][idx], trial_seqs[b_name][idx + 1] = v2, v1
                            feasible, starts = self._build_schedule_for_sequences(
                                trial_seqs, vessels_by_id, berths_by_name, outages
                            )
                            if feasible:
                                trial_plan = Plan(sequences=trial_seqs, planned_start=starts)
                                sim_res = simulate(
                                    vessels, berths, outages, policy=PlanPolicy(trial_plan)
                                )
                                if not sim_res.check_invariants() and not sim_res.unserved:
                                    obj = self.cost_model.evaluate(sim_res)
                                    if obj.J < best_score - 1e-4:
                                        best_score = obj.J
                                        current_seqs = trial_seqs
                                        best_plan = trial_plan
                                        best_sim = sim_res
                                        best_obj = obj
                                        improved = True
                                        break
                    if improved:
                        break

            if not improved:
                break

        # Calculate percentage improvements against FCFS baseline
        base_t = base_obj.T
        opt_t = best_obj.T
        wait_reduction_pct = 0.0 if base_t == 0 else 100.0 * (base_t - opt_t) / base_t

        base_e = base_obj.E
        opt_e = best_obj.E
        emiss_reduction_pct = 0.0 if base_e == 0 else 100.0 * (base_e - opt_e) / base_e

        base_c = base_obj.C
        opt_c = best_obj.C
        cost_reduction_pct = 0.0 if base_c == 0 else 100.0 * (base_c - opt_c) / base_c

        target_reduction = get_settings().targets.waiting_time_reduction_min_pct
        met_target = wait_reduction_pct >= target_reduction

        return OptimizationResult(
            plan=best_plan,
            sim_result=best_sim,
            fcfs_result=fcfs_result,
            objective=best_obj,
            baseline_objective=base_obj,
            waiting_time_reduction_pct=wait_reduction_pct,
            emissions_reduction_pct=emiss_reduction_pct,
            cost_reduction_pct=cost_reduction_pct,
            met_target=met_target,
            iterations_run=iterations,
        )
