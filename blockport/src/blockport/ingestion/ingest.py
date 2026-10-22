"""Persist validated feeds; quarantine rejects (report §5.1)."""
from __future__ import annotations

from datetime import datetime
from typing import List

from sqlalchemy.orm import Session

from ..models import AisObservation, QuarantinedRecord, WeatherObservation
from .validation import AisValidator, ValidationResult, WeatherValidator


def _jsonable(rec: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in rec.items()}


def _quarantine(session: Session, source: str, result: ValidationResult) -> None:
    session.add_all(
        QuarantinedRecord(source=source, reason=r.reason, payload=_jsonable(r.record))
        for r in result.rejected
    )


def ingest_ais(session: Session, records: List[dict], validator: AisValidator) -> ValidationResult:
    result = validator.validate(records)
    session.add_all(AisObservation(**r) for r in result.accepted)
    _quarantine(session, "ais", result)
    session.flush()
    return result


def ingest_weather(session: Session, records: List[dict],
                   validator: WeatherValidator) -> ValidationResult:
    result = validator.validate(records)
    session.add_all(WeatherObservation(**r) for r in result.accepted)
    _quarantine(session, "weather", result)
    session.flush()
    return result
