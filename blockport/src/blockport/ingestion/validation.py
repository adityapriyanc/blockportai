"""Data validation for ingested feeds (report §5.1, §6.1).

Rules: required fields/types, timezone-aware timestamps normalised to UTC, stale readings
discarded, future timestamps rejected, plausible ranges, duplicates, out-of-order readings and
physically impossible position jumps. Rejected records are returned with a reason so they can be
quarantined for audit rather than silently dropped.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

AIS_REQUIRED = ("vessel_id", "observed_at", "lat", "lon", "speed_knots", "heading_deg",
                "distance_to_port_nm")
WEATHER_REQUIRED = ("observed_at", "wind_speed_ms", "wind_dir_deg", "wave_height_m")


@dataclass
class Rejection:
    record: dict
    reason: str


@dataclass
class ValidationResult:
    accepted: List[dict] = field(default_factory=list)
    rejected: List[Rejection] = field(default_factory=list)

    def reasons(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for r in self.rejected:
            counts[r.reason] = counts.get(r.reason, 0) + 1
        return counts


def parse_timestamp(value: Union[str, datetime]) -> Tuple[Optional[datetime], Optional[str]]:
    """Return (UTC datetime, None) or (None, reason). Naive timestamps are ambiguous -> reject."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None, "invalid_timestamp"
    if not isinstance(value, datetime):
        return None, "invalid_timestamp"
    if value.tzinfo is None or value.utcoffset() is None:
        return None, "naive_timestamp"
    return value.astimezone(timezone.utc), None


def _num(rec: dict, key: str) -> Optional[float]:
    v = rec.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3440.065 * math.asin(math.sqrt(a))


class _BaseValidator:
    def __init__(self, now: Optional[datetime] = None, stale_after: Optional[timedelta] = None,
                 future_tolerance: timedelta = timedelta(minutes=5)):
        """`now`/`stale_after` None disables the staleness check (historical back-fill)."""
        self.now = now.astimezone(timezone.utc) if now else None
        self.stale_after = stale_after
        self.future_tolerance = future_tolerance

    def _time_checks(self, ts: datetime) -> Optional[str]:
        if self.now is not None:
            if ts > self.now + self.future_tolerance:
                return "future_timestamp"
            if self.stale_after is not None and ts < self.now - self.stale_after:
                return "stale"
        return None


class AisValidator(_BaseValidator):
    def __init__(self, *args: Any, max_speed_knots: float = 40.0,
                 max_implied_speed_knots: float = 60.0, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.max_speed_knots = max_speed_knots
        self.max_implied_speed_knots = max_implied_speed_knots
        self._last: Dict[Any, Tuple[datetime, float, float]] = {}
        self._seen: set = set()

    def check(self, rec: dict) -> Tuple[Optional[dict], Optional[str]]:
        for k in AIS_REQUIRED:
            if rec.get(k) is None:
                return None, "missing_field"
        ts, err = parse_timestamp(rec["observed_at"])
        if err:
            return None, err
        vals = {k: _num(rec, k) for k in AIS_REQUIRED if k not in ("vessel_id", "observed_at")}
        if any(v is None for v in vals.values()):
            return None, "invalid_type"
        if not (-90 <= vals["lat"] <= 90 and -180 <= vals["lon"] <= 180
                and 0 <= vals["speed_knots"] <= self.max_speed_knots
                and 0 <= vals["heading_deg"] <= 360 and vals["distance_to_port_nm"] >= 0):
            return None, "out_of_range"
        err = self._time_checks(ts)
        if err:
            return None, err
        vid = rec["vessel_id"]
        if (vid, ts) in self._seen:
            return None, "duplicate"
        last = self._last.get(vid)
        if last is not None:
            lt, llat, llon = last
            if ts < lt:
                return None, "out_of_order"
            hours = (ts - lt).total_seconds() / 3600
            if hours > 0 and _haversine_nm(llat, llon, vals["lat"], vals["lon"]) / hours \
                    > self.max_implied_speed_knots:
                return None, "position_jump"
        self._seen.add((vid, ts))
        self._last[vid] = (ts, vals["lat"], vals["lon"])
        return {**rec, **vals, "observed_at": ts}, None

    def validate(self, records: List[dict]) -> ValidationResult:
        """Records are processed in the given (arrival) order, so ordering faults are detectable."""
        res = ValidationResult()
        for rec in records:
            clean, reason = self.check(rec)
            if reason:
                res.rejected.append(Rejection(rec, reason))
            else:
                res.accepted.append(clean)
        return res


class WeatherValidator(_BaseValidator):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._seen: set = set()

    def check(self, rec: dict) -> Tuple[Optional[dict], Optional[str]]:
        for k in WEATHER_REQUIRED:
            if rec.get(k) is None:
                return None, "missing_field"
        ts, err = parse_timestamp(rec["observed_at"])
        if err:
            return None, err
        ws, wd, wh = (_num(rec, k) for k in ("wind_speed_ms", "wind_dir_deg", "wave_height_m"))
        tide = _num(rec, "tide_height_m") if rec.get("tide_height_m") is not None else 0.0
        if None in (ws, wd, wh, tide):
            return None, "invalid_type"
        if not (0 <= ws <= 80 and 0 <= wd <= 360 and 0 <= wh <= 30 and -10 <= tide <= 10):
            return None, "out_of_range"
        err = self._time_checks(ts)
        if err:
            return None, err
        if ts in self._seen:
            return None, "duplicate"
        self._seen.add(ts)
        return {"observed_at": ts, "wind_speed_ms": ws, "wind_dir_deg": wd,
                "wave_height_m": wh, "tide_height_m": tide}, None

    def validate(self, records: List[dict]) -> ValidationResult:
        res = ValidationResult()
        for rec in records:
            clean, reason = self.check(rec)
            if reason:
                res.rejected.append(Rejection(rec, reason))
            else:
                res.accepted.append(clean)
        return res
