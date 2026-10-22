"""Discrete-event port simulation (report §5.3).

Time advances from event to event (arrivals, service completions, outage ends, planned starts).
At each event the dispatch policy assigns waiting vessels to idle berths until no more
assignments are possible. Everything is deterministic: ties are broken by (arrival, vessel id)
and berth name, so the same inputs always give the same output.
"""
from __future__ import annotations

import heapq
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .model import Outage, Plan, TwinBerth, TwinVessel
from .results import SimResult, VesselRecord


class Context:
    """Read-only helpers a policy can use to check whether an assignment is allowed."""

    def __init__(self, outages: Iterable[Outage]):
        self._outages: Dict[str, List[Outage]] = {}
        for o in outages:
            self._outages.setdefault(o.berth, []).append(o)

    def eligible(self, v: TwinVessel, b: TwinBerth, now: datetime) -> bool:
        """Compatible, allowed, and the whole service window is free of outages."""
        if not b.fits(v) or (v.allowed_berths is not None and b.name not in v.allowed_berths):
            return False
        end = now + timedelta(hours=b.service_hours(v))
        return not any(o.start < end and o.end > now for o in self._outages.get(b.name, ()))


class FcfsPolicy:
    """First-come-first-served baseline (report §3 objectives 2-3: the comparison baseline).

    Vessels are considered in arrival order; each takes the smallest idle compatible berth that
    fits it. A vessel waits only for berths it can actually use, so one unservable vessel never
    blocks others.
    """

    def event_times(self) -> List[datetime]:
        return []

    def on_start(self, v: TwinVessel, b: TwinBerth) -> None:
        pass

    def select(self, now: datetime, waiting: Sequence[TwinVessel], idle: Sequence[TwinBerth],
               ctx: Context) -> Optional[Tuple[TwinVessel, TwinBerth]]:
        for v in sorted(waiting, key=lambda x: (x.arrival, x.id)):
            cands = [b for b in idle if ctx.eligible(v, b, now)]
            if cands:
                return v, min(cands, key=lambda b: (b.length_m, b.name))
        return None


class PlanPolicy:
    """Execute a berth plan: each berth serves its planned vessels in order.

    A vessel starts only when it has arrived, its berth is idle, it is next in that berth's
    sequence, and its planned start time has passed. If a planned vessel is late, the berth waits
    for it (this is what makes unexpected delays costly). Vessels absent from the plan are
    handled by the fallback policy on berths with no planned vessels left.
    """

    def __init__(self, plan: Plan, fallback: Optional[FcfsPolicy] = None):
        self.plan = plan.copy()
        self.fallback = fallback or FcfsPolicy()
        self.planned_ids = {vid for seq in self.plan.sequences.values() for vid in seq}

    def event_times(self) -> List[datetime]:
        return list(self.plan.planned_start.values())

    def on_start(self, v: TwinVessel, b: TwinBerth) -> None:
        seq = self.plan.sequences.get(b.name)
        if seq and seq[0] == v.id:
            seq.pop(0)

    def select(self, now: datetime, waiting: Sequence[TwinVessel], idle: Sequence[TwinBerth],
               ctx: Context) -> Optional[Tuple[TwinVessel, TwinBerth]]:
        by_id = {v.id: v for v in waiting}
        for b in sorted(idle, key=lambda x: x.name):
            seq = self.plan.sequences.get(b.name)
            if not seq:
                continue
            v = by_id.get(seq[0])
            if (v is not None and now >= self.plan.planned_start.get(v.id, now)
                    and ctx.eligible(v, b, now)):
                return v, b
        free = [b for b in idle if not self.plan.sequences.get(b.name)]
        unplanned = [v for v in waiting if v.id not in self.planned_ids]
        return self.fallback.select(now, unplanned, free, ctx)


def simulate(vessels: Sequence[TwinVessel], berths: Sequence[TwinBerth],
             outages: Sequence[Outage] = (), policy=None) -> SimResult:
    """Run the port from the first arrival until every servable vessel has been berthed."""
    policy = policy or FcfsPolicy()
    ctx = Context(outages)
    result = SimResult(vessels={v.id: v for v in vessels}, berths=list(berths),
                       outages=list(outages))
    pending = sorted(vessels, key=lambda v: (v.arrival, v.id))
    next_i = 0
    waiting: List[TwinVessel] = []
    current: Dict[str, datetime] = {}  # berth name -> time its current service ends

    events: List[datetime] = [v.arrival for v in vessels] + [o.end for o in outages]
    events += policy.event_times()
    heapq.heapify(events)

    while events:
        now = heapq.heappop(events)
        while events and events[0] == now:
            heapq.heappop(events)
        for name in [n for n, end in current.items() if end <= now]:
            del current[name]
        while next_i < len(pending) and pending[next_i].arrival <= now:
            waiting.append(pending[next_i])
            next_i += 1
        while True:
            idle = [b for b in berths if b.name not in current]
            choice = policy.select(now, waiting, idle, ctx)
            if choice is None:
                break
            v, b = choice
            svc = b.service_hours(v)
            end = now + timedelta(hours=svc)
            current[b.name] = end
            waiting.remove(v)
            heapq.heappush(events, end)
            policy.on_start(v, b)
            result.records.append(VesselRecord(v.id, b.name, v.arrival, now, end, svc, b.cranes))

    result.unserved = sorted(v.id for v in waiting) + sorted(v.id for v in pending[next_i:])
    result.records.sort(key=lambda r: (r.start, r.berth))
    return result
