"""Digital Twin data model (report §5.3): vessels, berths, outages, and berth plans.

These are plain immutable value objects, independent of the database, so scenarios can copy and
modify them freely ("what if" runs never touch operational data).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, FrozenSet, List, Optional

from ..domain import DEFAULT_CRANES_PER_BERTH, service_time_hours
from ..models import VesselType


@dataclass(frozen=True)
class TwinVessel:
    id: int
    name: str
    vessel_type: VesselType
    loa_m: float
    draft_m: float
    cargo_units: float
    arrival: datetime  # arrival time used by the simulation (actual, scheduled or predicted)
    predicted_arrival: Optional[datetime] = None  # ETA model output, for planning vs execution
    allowed_berths: Optional[FrozenSet[str]] = None  # None = any compatible berth
    fixed_service_hours: Optional[float] = None  # Explicit docking duration


@dataclass(frozen=True)
class TwinBerth:
    name: str
    terminal: str
    length_m: float
    depth_m: float
    compatible_types: FrozenSet[VesselType]
    cranes: int = DEFAULT_CRANES_PER_BERTH

    def fits(self, v: TwinVessel) -> bool:
        """Static compatibility: vessel type, length overall, draft (report §5.4 constraints)."""
        return (v.vessel_type in self.compatible_types and v.loa_m <= self.length_m
                and v.draft_m <= self.depth_m)

    def service_hours(self, v: TwinVessel) -> float:
        if v.fixed_service_hours is not None and v.fixed_service_hours > 0:
            return float(v.fixed_service_hours)
        return service_time_hours(v.vessel_type, v.cargo_units, self.cranes)


@dataclass(frozen=True)
class Outage:
    """A berth is unusable in [start, end): no service may overlap this window."""

    berth: str
    start: datetime
    end: datetime


@dataclass
class Plan:
    """A berth plan: ordered vessel ids per berth, with optional earliest start times.

    Executed by PlanPolicy. Vessels not mentioned in the plan fall back to FCFS.
    """

    sequences: Dict[str, List[int]] = field(default_factory=dict)
    planned_start: Dict[int, datetime] = field(default_factory=dict)

    def copy(self) -> "Plan":
        return Plan({b: list(s) for b, s in self.sequences.items()}, dict(self.planned_start))
