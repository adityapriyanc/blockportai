"""Simulation results and KPIs (report §5.3: waiting time, berth occupancy, utilization, delays).

The `activity` block records physical activity (vessel-hours waiting at anchor, berth-hours,
crane-hours) that Green Port Intelligence (Phase 6) converts into fuel/energy/CO2 estimates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np

from .model import Outage, TwinBerth, TwinVessel


@dataclass(frozen=True)
class VesselRecord:
    vessel_id: int
    berth: str
    arrival: datetime
    start: datetime
    end: datetime
    service_h: float
    cranes: int

    @property
    def wait_h(self) -> float:
        return (self.start - self.arrival).total_seconds() / 3600.0


@dataclass
class SimResult:
    vessels: Dict[int, TwinVessel]
    berths: List[TwinBerth]
    outages: List[Outage]
    records: List[VesselRecord] = field(default_factory=list)
    unserved: List[int] = field(default_factory=list)  # vessels that never got a berth

    def record_for(self, vessel_id: int) -> Optional[VesselRecord]:
        return next((r for r in self.records if r.vessel_id == vessel_id), None)

    def window(self) -> Tuple[datetime, datetime]:
        """Default measurement window: first arrival to last departure."""
        if not self.records:
            raise ValueError("no served vessels")
        return (min(r.arrival for r in self.records), max(r.end for r in self.records))

    def kpis(self, window: Optional[Tuple[datetime, datetime]] = None) -> Dict[str, object]:
        """Compute KPIs. Pass the same `window` to compare runs on equal footing; otherwise each
        run is measured over its own [first arrival, last departure]."""
        if not self.records:
            return {"n_served": 0, "n_unserved": len(self.unserved)}
        t0, t1 = window or self.window()
        win_h = (t1 - t0).total_seconds() / 3600.0
        waits = np.array([r.wait_h for r in self.records])

        busy: Dict[str, float] = {b.name: 0.0 for b in self.berths}
        for r in self.records:
            lo, hi = max(r.start, t0), min(r.end, t1)  # clip to window
            if hi > lo:
                busy[r.berth] += (hi - lo).total_seconds() / 3600.0
        per_berth = {n: h / win_h for n, h in busy.items()}

        wait_by_type: Dict[str, float] = {}
        berth_by_type: Dict[str, float] = {}
        crane_hours = 0.0
        for r in self.records:
            vt = self.vessels[r.vessel_id].vessel_type.value
            wait_by_type[vt] = wait_by_type.get(vt, 0.0) + r.wait_h
            berth_by_type[vt] = berth_by_type.get(vt, 0.0) + r.service_h
            if self.vessels[r.vessel_id].vessel_type.value == "container":
                crane_hours += r.cranes * r.service_h

        return {
            "n_served": len(self.records), "n_unserved": len(self.unserved),
            "avg_wait_h": float(waits.mean()), "total_wait_h": float(waits.sum()),
            "max_wait_h": float(waits.max()), "p95_wait_h": float(np.percentile(waits, 95)),
            "share_waiting": float((waits > 1e-9).mean()),
            "window_h": win_h,
            "berth_utilization": float(sum(busy.values()) / (win_h * len(self.berths))),
            "per_berth_utilization": per_berth,
            "avg_queue_length": float(waits.sum() / win_h),  # Little's law: integral of queue / T
            "cargo_handled": float(sum(self.vessels[r.vessel_id].cargo_units
                                       for r in self.records)),
            "activity": {
                "waiting_vessel_hours_by_type": wait_by_type,
                "berth_hours_by_type": berth_by_type,
                "container_crane_hours": crane_hours,
            },
        }

    def check_invariants(self) -> List[str]:
        """Return a list of violated physical/operational constraints (empty = consistent)."""
        problems: List[str] = []
        berth = {b.name: b for b in self.berths}
        by_berth: Dict[str, List[VesselRecord]] = {}
        for r in self.records:
            v = self.vessels[r.vessel_id]
            by_berth.setdefault(r.berth, []).append(r)
            if r.start < v.arrival:
                problems.append(f"vessel {v.id} started before arrival")
            if not berth[r.berth].fits(v):
                problems.append(f"vessel {v.id} incompatible with berth {r.berth}")
            if v.allowed_berths is not None and r.berth not in v.allowed_berths:
                problems.append(f"vessel {v.id} on disallowed berth {r.berth}")
            if abs((r.end - r.start).total_seconds() / 3600.0 - r.service_h) > 1e-9:
                problems.append(f"vessel {v.id} duration mismatch")
            for o in self.outages:
                if o.berth == r.berth and o.start < r.end and o.end > r.start:
                    problems.append(f"vessel {v.id} service overlaps outage on {o.berth}")
        for name, recs in by_berth.items():
            recs.sort(key=lambda r: r.start)
            for a, b in zip(recs, recs[1:]):
                if b.start < a.end - timedelta(microseconds=1):
                    problems.append(f"overlap on berth {name}: {a.vessel_id} / {b.vessel_id}")
        served = [r.vessel_id for r in self.records]
        if len(served) != len(set(served)):
            problems.append("a vessel was served more than once")
        if set(served) | set(self.unserved) != set(self.vessels):
            problems.append("some vessels are neither served nor unserved")
        return problems
