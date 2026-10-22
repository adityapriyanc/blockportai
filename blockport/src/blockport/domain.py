"""Shared domain rules: berth pools and cargo-handling (service) time.

Phase 3 uses these for congestion forecasting; the Digital Twin (Phase 4) and the optimizer
(Phase 5) reuse them so all components agree on how long a vessel occupies a berth.
Throughput rates are illustrative assumptions, to be calibrated per port.
"""
from __future__ import annotations

from typing import Dict

from .models import VesselType

POOL_CONTAINER = "container"
POOL_BULK_LIQUID = "bulk_liquid"

# Berths per pool in the synthetic layout (A1, A2, B1 | B2); see ingestion.synthetic.build_layout
POOL_CAPACITY: Dict[str, int] = {POOL_CONTAINER: 3, POOL_BULK_LIQUID: 1}

CRANE_MOVES_PER_HOUR = 30.0
DEFAULT_CRANES_PER_BERTH = 4

# cargo units handled per hour per berth (TEU/h for containers = cranes x moves/h, so the
# container entry below is the default 4-crane rate; tonnes/h otherwise)
THROUGHPUT_PER_BERTH: Dict[VesselType, float] = {
    VesselType.CONTAINER: DEFAULT_CRANES_PER_BERTH * CRANE_MOVES_PER_HOUR,
    VesselType.BULK: 6000.0,
    VesselType.TANKER: 6000.0,
    VesselType.LNG: 6000.0,
}
MOORING_OVERHEAD_H = 2.0  # berthing + unberthing


def pool_for_type(vessel_type: VesselType) -> str:
    return POOL_CONTAINER if vessel_type == VesselType.CONTAINER else POOL_BULK_LIQUID


def service_time_hours(vessel_type: VesselType, cargo_units: float,
                       cranes: int = DEFAULT_CRANES_PER_BERTH) -> float:
    """Hours a vessel occupies a berth: handling time plus mooring overhead.

    Container handling scales with the number of cranes working the berth; other cargo types use
    fixed shore-side throughput (pumps, conveyors), independent of cranes.
    """
    if cranes < 1:
        raise ValueError("a berth needs at least one crane (use an outage to close it)")
    if vessel_type == VesselType.CONTAINER:
        rate = cranes * CRANE_MOVES_PER_HOUR
    else:
        rate = THROUGHPUT_PER_BERTH[vessel_type]
    return MOORING_OVERHEAD_H + cargo_units / rate
