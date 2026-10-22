"""Dynamic re-optimization trigger (report §5.4).

Detects significant operational changes (revised ETAs, weather delays, berth outages)
and triggers re-optimization when the current operational plan becomes suboptimal or infeasible.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence

from ..twin.model import Outage, Plan, TwinVessel


@dataclass(frozen=True)
class ReoptimizationTrigger:
    triggered: bool
    reason: Optional[str]
    max_eta_deviation_minutes: float
    affected_vessel_ids: List[int]


def should_reoptimize(
    current_plan: Plan,
    vessels: Sequence[TwinVessel],
    updated_etas: Dict[int, datetime],
    new_outages: Sequence[Outage] = (),
    threshold_minutes: float = 30.0,
) -> ReoptimizationTrigger:
    """Evaluate whether an updated situation warrants re-running the berth optimizer.

    Triggers if:
    1. A planned vessel's ETA has shifted by >= threshold_minutes (e.g. 30m, report §3 obj 1).
    2. A new berth outage directly intersects a planned vessel's window.
    """
    vessels_by_id = {v.id: v for v in vessels}
    affected: List[int] = []
    max_dev = 0.0

    # 1. Check ETA shifts
    for vid, new_eta in updated_etas.items():
        v = vessels_by_id.get(vid)
        if not v:
            continue
        old_eta = v.predicted_arrival or v.arrival
        diff_min = abs((new_eta - old_eta).total_seconds()) / 60.0
        if diff_min > max_dev:
            max_dev = diff_min
        if diff_min >= threshold_minutes:
            affected.append(vid)

    if affected:
        msg = (
            f"{len(affected)} vessels have ETA deviation >= {threshold_minutes:g} min "
            f"(max: {max_dev:.1f} min)"
        )
        return ReoptimizationTrigger(
            triggered=True,
            reason=msg,
            max_eta_deviation_minutes=max_dev,
            affected_vessel_ids=affected,
        )

    # 2. Check outages intersecting planned start times
    for berth_name, seq in current_plan.sequences.items():
        for vid in seq:
            planned_start = current_plan.planned_start.get(vid)
            if not planned_start:
                continue
            v = vessels_by_id.get(vid)
            if not v:
                continue
            svc_duration = timedelta(hours=v.cargo_units / 120.0 + 2.0)
            planned_end = planned_start + svc_duration
            for o in new_outages:
                if o.berth == berth_name and o.start < planned_end and o.end > planned_start:
                    return ReoptimizationTrigger(
                        triggered=True,
                        reason=f"New outage on {berth_name} conflicts with planned vessel {vid}",
                        max_eta_deviation_minutes=0.0,
                        affected_vessel_ids=[vid],
                    )

    return ReoptimizationTrigger(
        triggered=False,
        reason=None,
        max_eta_deviation_minutes=max_dev,
        affected_vessel_ids=[],
    )
