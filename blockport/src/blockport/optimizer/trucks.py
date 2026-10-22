"""Ground transport (truck drayage) scheduling and coordination (report §2, §5.4, §7.3).

Synchronizes container vessel arrivals with inland gate appointments, truck dispatch windows,
and terminal traffic to avoid gate congestion and minimize truck idling and drayage miles.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List

from ..models import VesselType
from ..twin.results import SimResult
from .cost_model import TEU_PER_TRUCK, TRUCK_ROUNDTRIP_MILES


@dataclass(frozen=True)
class TruckSlotAssignment:
    port_call_id: int
    vessel_name: str
    terminal: str
    slot_start: datetime
    slot_end: datetime
    truck_count: int
    miles_per_truck: float
    total_truck_miles: float


class TruckScheduler:
    def __init__(self, slot_duration_hours: float = 2.0, max_trucks_per_slot: int = 200):
        self.slot_duration = timedelta(hours=slot_duration_hours)
        self.max_trucks_per_slot = max_trucks_per_slot

    def schedule_from_sim(
        self, sim_result: SimResult
    ) -> List[TruckSlotAssignment]:
        """Generate coordinated truck arrival windows aligned with vessel discharge times."""
        assignments: List[TruckSlotAssignment] = []
        berths_by_name = {b.name: b for b in sim_result.berths}

        for r in sim_result.records:
            v = sim_result.vessels[r.vessel_id]
            if v.vessel_type != VesselType.CONTAINER:
                continue

            berth = berths_by_name.get(r.berth)
            terminal = berth.terminal if berth else "Terminal A"
            miles_per_truck = TRUCK_ROUNDTRIP_MILES.get(terminal, 20.0)

            total_trucks = max(1, int(round(v.cargo_units / TEU_PER_TRUCK)))
            drayage_start = r.start + timedelta(hours=1.0)
            drayage_duration = max(timedelta(hours=2.0), r.end - drayage_start)

            secs_duration = drayage_duration.total_seconds()
            secs_slot = self.slot_duration.total_seconds()
            num_slots = max(1, int(secs_duration / secs_slot))
            trucks_per_slot = max(1, total_trucks // num_slots)
            rem = total_trucks % num_slots

            for i in range(num_slots):
                s_start = drayage_start + i * self.slot_duration
                s_end = s_start + self.slot_duration
                count = trucks_per_slot + (1 if i < rem else 0)
                assignments.append(
                    TruckSlotAssignment(
                        port_call_id=v.id,
                        vessel_name=v.name,
                        terminal=terminal,
                        slot_start=s_start,
                        slot_end=s_end,
                        truck_count=count,
                        miles_per_truck=miles_per_truck,
                        total_truck_miles=count * miles_per_truck,
                    )
                )

        return assignments
