"""Feature engineering for ETA prediction (report §5.2, §6.2).

One training row = one AIS observation of a vessel on approach ("snapshot"). Target = minutes
remaining until true arrival. Features use ONLY information available at the observation time:
current/recent speed and distance, observed weather, a (noisy, simulated) weather FORECAST along
the remaining journey, the carrier's published schedule, and calendar/vessel attributes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AisObservation, PortCall, Vessel, WeatherObservation

FEATURES: List[str] = [
    "distance_nm", "speed_knots", "speed_mean_6", "headwind_now", "headwind_past6",
    "headwind_fcst", "wind_speed", "wave_height", "hours_to_sched", "hour_of_day",
    "cargo_units", "carrier_code", "vtype_code",
]
CATEGORICAL: List[str] = ["carrier_code", "vtype_code"]
FORECAST_NOISE_SD_MS = 1.5  # simulated error of the weather forecast (m/s of headwind)


@dataclass
class Tables:
    calls: pd.DataFrame
    ais: pd.DataFrame
    weather: pd.DataFrame


def _utc(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, utc=True)  # naive values (SQLite) are interpreted as UTC


def load_tables(session: Session) -> Tables:
    calls = pd.DataFrame(session.execute(
        select(PortCall.id.label("call_id"), PortCall.vessel_id, PortCall.scheduled_eta,
               PortCall.actual_arrival, PortCall.cargo_units, Vessel.carrier,
               Vessel.vessel_type).join(Vessel, Vessel.id == PortCall.vessel_id)
    ).all(), columns=["call_id", "vessel_id", "scheduled_eta", "actual_arrival", "cargo_units",
                      "carrier", "vessel_type"])
    ais = pd.DataFrame(session.execute(
        select(AisObservation.port_call_id.label("call_id"), AisObservation.observed_at,
               AisObservation.speed_knots, AisObservation.heading_deg,
               AisObservation.distance_to_port_nm)
        .where(AisObservation.port_call_id.is_not(None))
    ).all(), columns=["call_id", "observed_at", "speed_knots", "heading_deg",
                      "distance_to_port_nm"])
    weather = pd.DataFrame(session.execute(
        select(WeatherObservation.observed_at, WeatherObservation.wind_speed_ms,
               WeatherObservation.wind_dir_deg, WeatherObservation.wave_height_m)
        .order_by(WeatherObservation.observed_at)
    ).all(), columns=["observed_at", "wind_speed_ms", "wind_dir_deg", "wave_height_m"])
    for df, cols in ((calls, ["scheduled_eta", "actual_arrival"]), (ais, ["observed_at"]),
                     (weather, ["observed_at"])):
        for c in cols:
            df[c] = _utc(df[c])
    calls["vessel_type"] = calls["vessel_type"].map(lambda v: getattr(v, "value", v))
    return Tables(calls, ais.sort_values(["call_id", "observed_at"]).reset_index(drop=True),
                  weather)


def build_snapshots(tables: Tables, seed: int = 0) -> pd.DataFrame:
    """Return one feature row per AIS observation, with remaining-time target and baselines."""
    rng = np.random.default_rng(seed)
    w = tables.weather.reset_index(drop=True)
    w0 = w["observed_at"].iloc[0]
    ws, wd = w["wind_speed_ms"].to_numpy(), w["wind_dir_deg"].to_numpy()
    wave = w["wave_height_m"].to_numpy()
    carriers = {c: i for i, c in enumerate(sorted(tables.calls["carrier"].unique()))}
    vtypes = {c: i for i, c in enumerate(sorted(tables.calls["vessel_type"].unique()))}
    calls = tables.calls.set_index("call_id")

    frames = []
    for call_id, g in tables.ais.groupby("call_id", sort=False):
        c = calls.loc[call_id]
        t = g["observed_at"]
        heading = float(g["heading_deg"].median())
        hw_series = ws * np.cos(np.radians(wd - heading))  # headwind per weather hour
        cs = np.concatenate([[0.0], np.cumsum(hw_series)])  # cs[k] = sum of hw_series[:k]
        last = len(ws) - 1
        idx = np.clip(((t - w0).dt.total_seconds() // 3600).to_numpy().astype(int), 0, last)

        dist = g["distance_to_port_nm"].to_numpy()
        spd = g["speed_knots"].to_numpy()
        k = np.clip(np.round(dist / np.maximum(spd, 1.0)), 1, 48).astype(int)
        end = np.clip(idx + k, 0, last + 1)
        start6 = np.clip(idx - 6, 0, last)
        fcst = (cs[end] - cs[idx]) / np.maximum(end - idx, 1)
        past6 = (cs[idx + 1] - cs[start6]) / np.maximum(idx + 1 - start6, 1)

        remaining = (c["actual_arrival"] - t).dt.total_seconds().to_numpy() / 60.0
        sched_remaining = (c["scheduled_eta"] - t).dt.total_seconds().to_numpy() / 60.0
        frames.append(pd.DataFrame({
            "call_id": call_id, "observed_at": t.to_numpy(),
            "distance_nm": dist, "speed_knots": spd,
            "speed_mean_6": pd.Series(spd).rolling(6, min_periods=1).mean().to_numpy(),
            "headwind_now": hw_series[idx], "headwind_past6": past6,
            "headwind_fcst": fcst + rng.normal(0, FORECAST_NOISE_SD_MS, len(g)),
            "wind_speed": ws[idx], "wave_height": wave[idx],
            "hours_to_sched": sched_remaining / 60.0,
            "hour_of_day": t.dt.hour.to_numpy(),
            "cargo_units": c["cargo_units"],
            "carrier_code": carriers[c["carrier"]], "vtype_code": vtypes[c["vessel_type"]],
            "remaining_min": remaining,
            "scheduled_remaining_min": sched_remaining,
            "naive_remaining_min": dist / np.maximum(spd, 1.0) * 60.0,
        }))
    out = pd.concat(frames, ignore_index=True)
    out["observed_at"] = pd.to_datetime(out["observed_at"], utc=True)
    return out


def time_split(tables: Tables, train: float = 0.70, val: float = 0.15
               ) -> Tuple[set, set, set]:
    """Chronological split BY PORT CALL (ordered by scheduled ETA): no random shuffling, and all
    snapshots of one call land in one partition, so there is no leakage across splits."""
    order = tables.calls.sort_values("scheduled_eta")["call_id"].tolist()
    n = len(order)
    a, b = int(n * train), int(n * (train + val))
    return set(order[:a]), set(order[a:b]), set(order[b:])
