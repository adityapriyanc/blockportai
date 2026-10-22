"""Relational domain schema (report §4, §5.1). This is the OFF-CHAIN store (report §4.12);
only hashes/references of selected records are anchored on the blockchain (Phase 7).

All timestamps are timezone-aware UTC (report §5.1: timestamps must be reconcilable).
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class VesselType(str, enum.Enum):
    CONTAINER = "container"
    BULK = "bulk"
    TANKER = "tanker"
    LNG = "lng"


class PortCallStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    EN_ROUTE = "en_route"
    ANCHORED = "anchored"
    BERTHED = "berthed"
    DEPARTED = "departed"
    CANCELLED = "cancelled"


class RecommendationStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    MODIFIED = "modified"
    REJECTED = "rejected"


class Terminal(Base):
    __tablename__ = "terminals"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    berths: Mapped[List["Berth"]] = relationship(back_populates="terminal")
    equipment: Mapped[List["Equipment"]] = relationship(back_populates="terminal")


class Berth(Base):
    __tablename__ = "berths"
    id: Mapped[int] = mapped_column(primary_key=True)
    terminal_id: Mapped[int] = mapped_column(ForeignKey("terminals.id"))
    name: Mapped[str] = mapped_column(String(64), unique=True)
    length_m: Mapped[float] = mapped_column(Float)
    depth_m: Mapped[float] = mapped_column(Float)
    compatible_types: Mapped[list] = mapped_column(JSON)  # list of VesselType values
    terminal: Mapped[Terminal] = relationship(back_populates="berths")


class Equipment(Base):
    """Cranes and other cargo-handling equipment (capacity in moves/hour)."""

    __tablename__ = "equipment"
    id: Mapped[int] = mapped_column(primary_key=True)
    terminal_id: Mapped[int] = mapped_column(ForeignKey("terminals.id"))
    kind: Mapped[str] = mapped_column(String(32))
    capacity_moves_per_hour: Mapped[float] = mapped_column(Float)
    power_kw: Mapped[float] = mapped_column(Float, default=0.0)
    operational: Mapped[bool] = mapped_column(default=True)
    terminal: Mapped[Terminal] = relationship(back_populates="equipment")


class Vessel(Base):
    __tablename__ = "vessels"
    id: Mapped[int] = mapped_column(primary_key=True)
    imo: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    vessel_type: Mapped[VesselType] = mapped_column(Enum(VesselType))
    carrier: Mapped[str] = mapped_column(String(64))
    loa_m: Mapped[float] = mapped_column(Float)
    draft_m: Mapped[float] = mapped_column(Float)
    port_calls: Mapped[List["PortCall"]] = relationship(back_populates="vessel")


class PortCall(Base):
    __tablename__ = "port_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    vessel_id: Mapped[int] = mapped_column(ForeignKey("vessels.id"))
    berth_id: Mapped[Optional[int]] = mapped_column(ForeignKey("berths.id"), nullable=True)
    scheduled_eta: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    _ts = DateTime(timezone=True)
    predicted_eta: Mapped[Optional[datetime]] = mapped_column(_ts, nullable=True)
    actual_arrival: Mapped[Optional[datetime]] = mapped_column(_ts, nullable=True)
    berth_start: Mapped[Optional[datetime]] = mapped_column(_ts, nullable=True)
    departure: Mapped[Optional[datetime]] = mapped_column(_ts, nullable=True)
    cargo_units: Mapped[float] = mapped_column(Float)  # e.g. TEU or tonnes
    status: Mapped[PortCallStatus] = mapped_column(
        Enum(PortCallStatus), default=PortCallStatus.SCHEDULED
    )
    vessel: Mapped[Vessel] = relationship(back_populates="port_calls")


class AisObservation(Base):
    __tablename__ = "ais_observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    vessel_id: Mapped[int] = mapped_column(ForeignKey("vessels.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    speed_knots: Mapped[float] = mapped_column(Float)
    heading_deg: Mapped[float] = mapped_column(Float)
    distance_to_port_nm: Mapped[float] = mapped_column(Float)
    port_call_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("port_calls.id"), nullable=True, index=True
    )


class WeatherObservation(Base):
    __tablename__ = "weather_observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    wind_speed_ms: Mapped[float] = mapped_column(Float)
    wind_dir_deg: Mapped[float] = mapped_column(Float)
    wave_height_m: Mapped[float] = mapped_column(Float)
    tide_height_m: Mapped[float] = mapped_column(Float, default=0.0)


class EnergyRecord(Base):
    __tablename__ = "energy_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source: Mapped[str] = mapped_column(String(64))  # equipment/vessel/truck identifier
    kind: Mapped[str] = mapped_column(String(32))  # fuel_kg | electricity_kwh | diesel_litres
    quantity: Mapped[float] = mapped_column(Float)
    port_call_id: Mapped[Optional[int]] = mapped_column(ForeignKey("port_calls.id"), nullable=True)


class TruckSchedule(Base):
    __tablename__ = "truck_schedules"
    id: Mapped[int] = mapped_column(primary_key=True)
    port_call_id: Mapped[int] = mapped_column(ForeignKey("port_calls.id"))
    terminal_id: Mapped[int] = mapped_column(ForeignKey("terminals.id"))
    slot_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    truck_count: Mapped[int] = mapped_column(Integer)


class QuarantinedRecord(Base):
    """Records rejected by validation (report §5.1) kept for audit, not used downstream."""

    __tablename__ = "quarantined_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(JSON)


class Recommendation(Base):
    __tablename__ = "recommendations"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    port_call_id: Mapped[Optional[int]] = mapped_column(ForeignKey("port_calls.id"), nullable=True)
    plan: Mapped[dict] = mapped_column(JSON)  # structured optimizer output
    metrics: Mapped[dict] = mapped_column(JSON)  # wait saved, CO2 delta, cost, uncertainties
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[RecommendationStatus] = mapped_column(
        Enum(RecommendationStatus), default=RecommendationStatus.PENDING
    )


class Approval(Base):
    """Human-in-the-loop decision (report §5.7): approve / modify / reject."""

    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id"))
    operator: Mapped[str] = mapped_column(String(64))
    decision: Mapped[RecommendationStatus] = mapped_column(Enum(RecommendationStatus))
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    modified_plan: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class ChainRecord(Base):
    """Off-chain pointer to an on-chain anchor (report §5.6): hash + reference only."""

    __tablename__ = "chain_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    record_type: Mapped[str] = mapped_column(String(32))  # approval | docking | emissions | ...
    subject_table: Mapped[str] = mapped_column(String(64))
    subject_id: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))  # SHA-256 hex
    tx_hash: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    anchored_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
