"""Sync the Digital Twin with the operational database (report §5.3: 'how frequently its
information is updated'). Builds twin objects from stored port calls and berths.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Berth, Equipment, PortCall, Vessel, VesselType
from ..timeutil import ensure_utc
from .model import TwinBerth, TwinVessel

ArrivalSource = Literal["actual", "scheduled"]


def berths_from_db(session: Session) -> List[TwinBerth]:
    """Cranes per berth = operational gantry cranes in the terminal / berths in the terminal."""
    out: List[TwinBerth] = []
    berths = session.execute(select(Berth).order_by(Berth.name)).scalars().all()
    per_terminal: Dict[int, int] = {}
    for b in berths:
        per_terminal[b.terminal_id] = per_terminal.get(b.terminal_id, 0) + 1
    for b in berths:
        cranes = session.query(Equipment).filter(
            Equipment.terminal_id == b.terminal_id, Equipment.kind == "gantry_crane",
            Equipment.operational.is_(True)).count()
        out.append(TwinBerth(
            name=b.name, terminal=b.terminal.name, length_m=b.length_m, depth_m=b.depth_m,
            compatible_types=frozenset(VesselType(t) for t in b.compatible_types),
            cranes=max(1, cranes // per_terminal[b.terminal_id]),
        ))
    return out


def vessels_from_db(
    session: Session, arrival: ArrivalSource = "actual",
    predicted_etas: Optional[Dict[int, datetime]] = None,
) -> List[TwinVessel]:
    """One TwinVessel per port call (id = port call id).

    `arrival` selects which timestamp drives the simulation: the true arrival (to evaluate
    outcomes) or the carrier schedule. `predicted_etas` (call id -> ETA from the Phase 3 model)
    is attached for planning.
    """
    rows = session.execute(
        select(PortCall, Vessel).join(Vessel, Vessel.id == PortCall.vessel_id)
        .order_by(PortCall.id)
    ).all()
    out: List[TwinVessel] = []
    for call, v in rows:
        when = call.actual_arrival if arrival == "actual" else call.scheduled_eta
        if when is None:
            continue
        pred = (predicted_etas or {}).get(call.id)
        out.append(TwinVessel(
            id=call.id, name=v.name, vessel_type=v.vessel_type, loa_m=v.loa_m, draft_m=v.draft_m,
            cargo_units=call.cargo_units, arrival=ensure_utc(when),
            predicted_arrival=ensure_utc(pred) if pred else None,
        ))
    return out
