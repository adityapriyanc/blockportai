"""Synthetic port data generator (Phase 2, report §5.1/§6.1/§8.2).

The report calls for "historical or simulated" data. Vessel arrival times here EMERGE from a simple
physical approach model (speed reduced by headwind, plus noise) so that an ETA model (Phase 3) can
learn real structure from AIS position/speed and weather instead of memorising a formula.

Realism parameters borrowed from the report's Section 8 context (carrier reliability ranking from
Sea-Intelligence GLP issue 181: Maersk 67.3%, Hapag-Lloyd 61.5%, MSC 55.2%, CMA CGM 50.6%,
Wan Hai 23.2%) and "burst congestion" (CPPI 2025): delayed vessels bunch into short windows.
Late-delay magnitudes are SCALED DOWN (hours, not days) because the simulation window is days.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
from sqlalchemy.orm import Session

from ..models import (
    AisObservation,
    Berth,
    Equipment,
    PortCall,
    PortCallStatus,
    Terminal,
    Vessel,
    VesselType,
    WeatherObservation,
)

PORT_LAT, PORT_LON = 1.20, 103.70  # fictional-ish port location
NM_PER_DEG_LAT = 60.0

# carrier -> probability a call is on time (report §8.1 figures; others interpolated)
CARRIER_RELIABILITY: Dict[str, float] = {
    "Maersk": 0.673, "Hapag-Lloyd": 0.615, "MSC": 0.552, "CMA CGM": 0.506,
    "ONE": 0.45, "Evergreen": 0.40, "COSCO": 0.38, "Wan Hai": 0.232,
}

VESSEL_SPECS = {  # type: (loa range m, draft range m, cargo range, service speed kn)
    VesselType.CONTAINER: ((200, 380), (10, 15.5), (600, 4200), 16.0),  # TEU handled per call
    VesselType.BULK: ((180, 300), (10, 17), (30000, 150000), 12.5),
    VesselType.TANKER: ((180, 330), (11, 16.5), (40000, 200000), 13.0),
    VesselType.LNG: ((240, 300), (11, 12.5), (80000, 170000), 17.0),
}


# ----------------------------------------------------------------------------- layout
def build_layout(session: Session) -> Dict[str, Berth]:
    """Two terminals (report §7): A (2 container berths), B (1 container + 1 bulk/tanker)."""
    ta, tb = Terminal(name="Terminal A"), Terminal(name="Terminal B")
    c = [VesselType.CONTAINER.value]
    berths = [
        Berth(terminal=ta, name="A1", length_m=400, depth_m=16.0, compatible_types=c),
        Berth(terminal=ta, name="A2", length_m=350, depth_m=15.0, compatible_types=c),
        Berth(terminal=tb, name="B1", length_m=330, depth_m=14.5, compatible_types=c),
        Berth(terminal=tb, name="B2", length_m=330, depth_m=17.0,
              compatible_types=[VesselType.BULK.value, VesselType.TANKER.value,
                                VesselType.LNG.value]),
    ]
    # 8 cranes per terminal = 4 per berth (see domain.DEFAULT_CRANES_PER_BERTH)
    equipment = [Equipment(terminal=t, kind="gantry_crane", capacity_moves_per_hour=30,
                           power_kw=400.0) for t in (ta, tb) for _ in range(8)]
    session.add_all([ta, tb, *berths, *equipment])
    session.flush()
    return {b.name: b for b in berths}


def build_fleet(session: Session, rng: np.random.Generator, n: int = 60) -> List[Vessel]:
    carriers = list(CARRIER_RELIABILITY)
    types = [VesselType.CONTAINER] * 10 + [VesselType.BULK, VesselType.TANKER, VesselType.LNG]
    fleet = []
    for i in range(n):
        vt = types[int(rng.integers(len(types)))]
        loa_r, draft_r, _, _ = VESSEL_SPECS[vt]
        fleet.append(Vessel(
            imo=f"IMO{9000000 + i}", name=f"MV Synthetic {i:03d}", vessel_type=vt,
            carrier=carriers[int(rng.integers(len(carriers)))],
            loa_m=round(float(rng.uniform(*loa_r)), 1),
            draft_m=round(float(rng.uniform(*draft_r)), 1),
        ))
    session.add_all(fleet)
    session.flush()
    return fleet


# ----------------------------------------------------------------------------- weather
@dataclass
class WeatherSeries:
    start: datetime
    wind_speed: np.ndarray  # m/s hourly
    wind_dir: np.ndarray  # degrees, direction wind blows FROM
    wave_height: np.ndarray
    tide: np.ndarray

    def index(self, t: datetime) -> int:
        i = int((t - self.start).total_seconds() // 3600)
        return min(max(i, 0), len(self.wind_speed) - 1)

    def at(self, t: datetime) -> Tuple[float, float]:
        i = self.index(t)
        return float(self.wind_speed[i]), float(self.wind_dir[i])

    def records(self) -> List[dict]:
        return [
            {"observed_at": self.start + timedelta(hours=i),
             "wind_speed_ms": round(float(self.wind_speed[i]), 2),
             "wind_dir_deg": round(float(self.wind_dir[i]), 1),
             "wave_height_m": round(float(self.wave_height[i]), 2),
             "tide_height_m": round(float(self.tide[i]), 2)}
            for i in range(len(self.wind_speed))
        ]


def generate_weather(rng: np.random.Generator, start: datetime, hours: int) -> WeatherSeries:
    """AR(1) wind speed (storm episodes), slowly rotating direction, waves tied to wind."""
    ws = np.empty(hours)
    ws[0] = 6.0
    for i in range(1, hours):
        ws[i] = max(0.0, 6.0 + 0.95 * (ws[i - 1] - 6.0) + rng.normal(0, 1.2))
    wd = (np.cumsum(rng.normal(0, 8, hours)) + rng.uniform(0, 360)) % 360
    waves = np.clip(0.1 * ws + rng.normal(0, 0.15, hours), 0.1, None)
    tide = 1.2 * np.sin(2 * math.pi * np.arange(hours) / 12.42)
    return WeatherSeries(start, ws, wd, waves, tide)


# ----------------------------------------------------------------------------- approach
HEADWIND_SPEED_LOSS = 0.012  # fractional speed loss per m/s of headwind (illustrative)


def headwind_ms(wind_speed: float, wind_dir_from: float, heading_deg: float) -> float:
    """Positive = headwind, negative = tailwind."""
    return wind_speed * math.cos(math.radians(wind_dir_from - heading_deg))


def position_for(distance_nm: float, heading_deg: float) -> Tuple[float, float]:
    """Lat/lon of a vessel `distance_nm` out from the port, approaching on `heading_deg`."""
    h = math.radians(heading_deg)
    lat = PORT_LAT - distance_nm * math.cos(h) / NM_PER_DEG_LAT
    lon = PORT_LON - distance_nm * math.sin(h) / (NM_PER_DEG_LAT * math.cos(math.radians(PORT_LAT)))
    return lat, lon


def simulate_approach(
    rng: np.random.Generator, vessel_id: int, t0: datetime, start_distance_nm: float,
    heading_deg: float, service_speed_kn: float, weather: WeatherSeries, step_min: int = 30,
) -> Tuple[List[dict], datetime]:
    """Step a vessel toward the port; return AIS records and its TRUE arrival time."""
    obs: List[dict] = []
    t, dist = t0, start_distance_nm
    step_h = step_min / 60.0
    while True:
        ws, wd = weather.at(t)
        hw = headwind_ms(ws, wd, heading_deg)
        speed = max(1.0, service_speed_kn * (1 - HEADWIND_SPEED_LOSS * hw) + rng.normal(0, 0.3))
        lat, lon = position_for(dist, heading_deg)
        obs.append({
            "vessel_id": vessel_id, "observed_at": t, "lat": round(lat, 5), "lon": round(lon, 5),
            "speed_knots": round(speed, 2), "heading_deg": round(heading_deg, 1),
            "distance_to_port_nm": round(dist, 2),
        })
        travelled = speed * step_h
        if travelled >= dist:
            return obs, t + timedelta(hours=dist / speed)
        dist -= travelled
        t += timedelta(minutes=step_min)


# ----------------------------------------------------------------------------- generator
@dataclass
class SeedSummary:
    vessels: int
    port_calls: int
    ais_observations: int
    weather_observations: int


def _start_times(rng: np.random.Generator, start: datetime, days: int) -> List[datetime]:
    """~1.8 approaches/day with occasional bursts (3-5 vessels within 6h): report §8.2.

    The base rate keeps average berth load near ~60% of the 4-berth capacity so that congestion
    arises mainly from bursts, as described by the CPPI 'burst congestion' observation.
    """
    times: List[datetime] = []
    for d in range(days):
        day0 = start + timedelta(days=d)
        for _ in range(int(rng.poisson(1.8))):
            times.append(day0 + timedelta(hours=float(rng.uniform(0, 24))))
        if rng.random() < 0.15:
            anchor = day0 + timedelta(hours=float(rng.uniform(0, 18)))
            for _ in range(int(rng.integers(3, 6))):
                times.append(anchor + timedelta(hours=float(rng.uniform(0, 6))))
    return sorted(times)


def seed_database(
    session: Session, days: int = 30, seed: int = 42, start: Optional[datetime] = None,
    mean_late_hours: float = 8.0, start_distance_nm: Tuple[float, float] = (350, 700),
) -> SeedSummary:
    rng = np.random.default_rng(seed)
    start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    build_layout(session)
    fleet = build_fleet(session, rng)
    weather = generate_weather(rng, start - timedelta(days=1), (days + 8) * 24)
    session.add_all(WeatherObservation(**r) for r in weather.records())

    n_calls = n_obs = 0
    busy_until: Dict[int, datetime] = {}  # a vessel cannot approach twice at once
    for t0 in _start_times(rng, start, days):
        free = [v for v in fleet if busy_until.get(v.id, t0) <= t0]
        if not free:
            continue
        vessel = free[int(rng.integers(len(free)))]
        _, _, cargo_r, speed = VESSEL_SPECS[vessel.vessel_type]
        d0 = float(rng.uniform(*start_distance_nm))
        heading = float(rng.choice([45, 90, 135, 180, 225])) + float(rng.normal(0, 5))
        obs, arrival = simulate_approach(rng, vessel.id, t0, d0, heading, speed, weather)

        nominal = t0 + timedelta(hours=d0 / speed)
        on_time = rng.random() < CARRIER_RELIABILITY[vessel.carrier]
        late_h = 0.0 if on_time else float(rng.exponential(mean_late_hours))
        scheduled = nominal - timedelta(hours=late_h) + timedelta(hours=float(rng.normal(0, 0.5)))

        call = PortCall(
            vessel=vessel, scheduled_eta=scheduled, actual_arrival=arrival,
            cargo_units=round(float(rng.uniform(*cargo_r)), 0), status=PortCallStatus.DEPARTED,
        )
        session.add(call)
        session.flush()  # assign call.id: the voyage association real AIS feeds lack
        busy_until[vessel.id] = arrival + timedelta(days=3)
        session.add_all(AisObservation(**o, port_call_id=call.id) for o in obs)
        n_calls += 1
        n_obs += len(obs)
    session.flush()
    return SeedSummary(len(fleet), n_calls, n_obs, len(weather.wind_speed))
