"""Maritime Physics & GPS Predictive Intelligence Model.

Calculates precise, deterministic and quantile-bounded parameter modifications
for incoming and berthed vessels based on:
1. Hypothetical GPS Kinematic Navigation (Haversine Great-Circle, SOG, COG, distance).
2. Naval Architecture Hydrodynamic & Aerodynamic Speed Loss (Kwon/Townsin empirical formulation).
3. MetOcean Physical Conditions (wind vectors, headwind component, wave height Hs, visibility).
4. Port Fairway & Quayside Conditions (traffic density, tidal windows, crane wind-derating).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..domain import CRANE_MOVES_PER_HOUR, DEFAULT_CRANES_PER_BERTH, MOORING_OVERHEAD_H, service_time_hours
from ..models import VesselType


# Reference Port Fairway Anchorage Coordinates (e.g., North Sea Approach)
DEFAULT_PORT_LAT = 53.5461
DEFAULT_PORT_LON = 9.9238


@dataclass
class VesselGpsState:
    """Hypothetical GPS telemetry snapshot for approaching vessel."""
    lat: float
    lon: float
    sog_knots: float  # Speed Over Ground
    cog_deg: float    # Course Over Ground
    heading_deg: float
    nominal_cruising_speed_knots: float = 18.0
    vessel_id: Optional[int] = None
    vessel_name: Optional[str] = None
    distance_to_port_nmi: Optional[float] = None

    def calculate_great_circle_distance(self, target_lat: float = DEFAULT_PORT_LAT,
                                        target_lon: float = DEFAULT_PORT_LON) -> float:
        """Haversine formula to compute exact distance in nautical miles (nmi)."""
        r_earth_nmi = 3440.065  # Earth radius in nautical miles
        phi1 = math.radians(self.lat)
        phi2 = math.radians(target_lat)
        delta_phi = math.radians(target_lat - self.lat)
        delta_lambda = math.radians(target_lon - self.lon)

        a = (math.sin(delta_phi / 2.0) ** 2 +
             math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
        dist = r_earth_nmi * c
        self.distance_to_port_nmi = round(dist, 2)
        return self.distance_to_port_nmi

    def calculate_bearing_to_port(self, target_lat: float = DEFAULT_PORT_LAT,
                                  target_lon: float = DEFAULT_PORT_LON) -> float:
        """Initial bearing (forward azimuth) from current GPS position to port."""
        phi1 = math.radians(self.lat)
        phi2 = math.radians(target_lat)
        delta_lambda = math.radians(target_lon - self.lon)

        y = math.sin(delta_lambda) * math.cos(phi2)
        x = (math.cos(phi1) * math.sin(phi2) -
             math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda))
        initial_bearing = math.degrees(math.atan2(y, x))
        return round((initial_bearing + 360.0) % 360.0, 1)


@dataclass
class MetOceanConditions:
    """Real-time physical weather and sea conditions."""
    wind_speed_knots: float = 14.2
    wind_direction_deg: float = 240.0  # Direction wind is coming FROM
    wave_height_m: float = 0.8         # Significant wave height Hs
    visibility_nmi: float = 10.0       # Nautical miles visibility
    condition_label: str = "CLEAR"     # CLEAR | RAIN | FOG | GALE | STORM
    sea_temperature_c: float = 12.0


@dataclass
class PortOperationalCondition:
    """Physical and operational state of the port fairways and berths."""
    channel_congestion_factor: float = 0.1  # 0.0 (empty) to 1.0 (heavily congested)
    pilot_wait_hours: float = 0.0           # Pilot boarding station delay
    tidal_restriction_active: bool = False
    tidal_window_delay_hours: float = 0.0   # Wait for high tide if draft > threshold
    crane_health_pct: float = 100.0         # Mechanical availability of quay cranes


@dataclass
class PhysicsPredictionResult:
    """Comprehensive, explainable prediction output with physical breakdown."""
    # Modified Times
    original_eta_hours: float
    predicted_eta_hours: float
    eta_delta_minutes: float
    eta_confidence_band: Dict[str, str]  # p10, p50, p90 in UTC formatted

    # Modified Docking Service
    nominal_dock_duration_hours: float
    predicted_dock_duration_hours: float
    dock_duration_delta_hours: float

    # Departure Prediction
    predicted_etd_hours: float

    # Speed & Hydrodynamic Breakdown
    distance_remaining_nmi: float
    nominal_speed_knots: float
    effective_sog_knots: float
    speed_loss_knots: float
    speed_loss_pct: float

    # Physical components
    headwind_speed_knots: float
    wind_drag_speed_loss_knots: float
    wave_resistance_speed_loss_knots: float
    visibility_safety_cap_knots: Optional[float]
    crane_weather_derating_pct: float

    # Audit & Narrative
    physics_audit_log: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_eta_hours": self.original_eta_hours,
            "predicted_eta_hours": self.predicted_eta_hours,
            "eta_delta_minutes": self.eta_delta_minutes,
            "eta_confidence_band": self.eta_confidence_band,
            "nominal_dock_duration_hours": self.nominal_dock_duration_hours,
            "predicted_dock_duration_hours": self.predicted_dock_duration_hours,
            "dock_duration_delta_hours": self.dock_duration_delta_hours,
            "predicted_etd_hours": self.predicted_etd_hours,
            "distance_remaining_nmi": self.distance_remaining_nmi,
            "nominal_speed_knots": self.nominal_speed_knots,
            "effective_sog_knots": self.effective_sog_knots,
            "speed_loss_knots": self.speed_loss_knots,
            "speed_loss_pct": self.speed_loss_pct,
            "headwind_speed_knots": self.headwind_speed_knots,
            "wind_drag_speed_loss_knots": self.wind_drag_speed_loss_knots,
            "wave_resistance_speed_loss_knots": self.wave_resistance_speed_loss_knots,
            "visibility_safety_cap_knots": self.visibility_safety_cap_knots,
            "crane_weather_derating_pct": self.crane_weather_derating_pct,
            "physics_audit_log": self.physics_audit_log,
        }


class MaritimePhysicsPredictor:
    """Predictive model implementing Kwon's speed loss and quayside weather derating."""

    def __init__(self, port_lat: float = DEFAULT_PORT_LAT, port_lon: float = DEFAULT_PORT_LON):
        self.port_lat = port_lat
        self.port_lon = port_lon

    def predict_vessel_parameters(
        self,
        vessel_type: VesselType,
        loa_m: float,
        draft_m: float,
        cargo_units: float,
        gps_state: VesselGpsState,
        weather: MetOceanConditions,
        port_cond: PortOperationalCondition,
        nominal_eta_hours: float,
        cranes_assigned: int = DEFAULT_CRANES_PER_BERTH,
        fixed_service_hours: Optional[float] = None,
        base_clock_hour: float = 8.0,
    ) -> PhysicsPredictionResult:
        """Execute deterministic physics + quantile uncertainty prediction."""
        audit_log: List[str] = []

        # 1. GPS Distance Calculation
        if gps_state.distance_to_port_nmi is not None and gps_state.distance_to_port_nmi > 0:
            dist_nmi = gps_state.distance_to_port_nmi
        else:
            dist_nmi = gps_state.calculate_great_circle_distance(self.port_lat, self.port_lon)

        bearing_to_port = gps_state.calculate_bearing_to_port(self.port_lat, self.port_lon)
        effective_heading = gps_state.heading_deg if gps_state.heading_deg is not None else bearing_to_port
        audit_log.append(f"GPS Nav: Distance to anchorage = {dist_nmi:.2f} nmi, Waypoint Bearing = {bearing_to_port:.1f}°.")

        # 2. Aerodynamic Wind Resistance (Headwind calculation)
        wind_angle_rel = math.radians((weather.wind_direction_deg - effective_heading) % 360.0)
        headwind_knots = weather.wind_speed_knots * math.cos(wind_angle_rel)
        v_nom = max(5.0, gps_state.nominal_cruising_speed_knots)

        # Aerodynamic speed loss factor
        if headwind_knots > 0:
            wind_speed_loss = min(v_nom * 0.40, (0.012 * headwind_knots * (loa_m / 300.0)))
        else:
            wind_speed_loss = max(-0.5, 0.004 * headwind_knots)

        # 3. Hydrodynamic Wave Resistance (Kwon's formulation)
        hs = max(0.0, weather.wave_height_m)
        blockiness = 0.65 if vessel_type == VesselType.CONTAINER else (0.82 if vessel_type == VesselType.BULK else 0.78)
        wave_speed_loss = min(v_nom * 0.45, 0.55 * (hs ** 1.6) * (blockiness / 0.70))

        total_physics_loss = max(0.0, wind_speed_loss + wave_speed_loss)

        # 4. Visibility Safety Cap (Pilotage & Channel Safety Regulations)
        visibility_cap: Optional[float] = None
        if weather.visibility_nmi < 1.5:
            visibility_cap = 6.0  # Severe fog protocol: max 6 knots
            audit_log.append("Pilotage Safety: Dense fog (vis < 1.5 nmi). Approach speed capped at 6.0 kn.")
        elif weather.visibility_nmi < 3.0:
            visibility_cap = 9.0  # Moderate fog: max 9 knots
            audit_log.append("Pilotage Safety: Restricted visibility (< 3.0 nmi). Speed capped at 9.0 kn.")

        # Effective SOG calculation
        sog_predicted = max(3.0, v_nom - total_physics_loss)
        if visibility_cap is not None:
            sog_predicted = min(sog_predicted, visibility_cap)

        actual_loss = max(0.0, v_nom - sog_predicted)
        loss_pct = (actual_loss / v_nom) * 100.0

        audit_log.append(
            f"Hydro/Aerodynamics: Headwind = {headwind_knots:+.1f} kn, Wave Hs = {hs:.1f}m. "
            f"Speed loss = {actual_loss:.2f} kn ({loss_pct:.1f}% reduction). Effective SOG = {sog_predicted:.2f} kn."
        )

        # 5. Precise Arrival Transit Time
        transit_hours = dist_nmi / sog_predicted

        # Port channel & pilot delay
        approach_channel_hold = (
            port_cond.pilot_wait_hours +
            (port_cond.channel_congestion_factor * 1.5) +  # up to 1.5h hold for busy fairway
            (port_cond.tidal_window_delay_hours if (draft_m > 14.5 and port_cond.tidal_restriction_active) else 0.0)
        )
        if approach_channel_hold > 0:
            audit_log.append(f"Fairway Logistics: Channel delay = +{approach_channel_hold:.2f}h (pilot/tide/traffic).")

        predicted_arrival_hours = round(base_clock_hour + transit_hours + approach_channel_hold, 2)
        eta_delta_minutes = round((predicted_arrival_hours - nominal_eta_hours) * 60.0, 1)

        # Quantile Uncertainty Bands (p10, p50, p90)
        uncertainty_spread_h = 0.15 + (transit_hours * 0.08) * (1.0 + (hs / 3.0))
        p10_h = max(base_clock_hour, predicted_arrival_hours - uncertainty_spread_h)
        p50_h = predicted_arrival_hours
        p90_h = predicted_arrival_hours + uncertainty_spread_h

        def fmt_utc(h: float) -> str:
            hour = int(h % 24)
            minute = int(round((h % 1.0) * 60.0)) % 60
            return f"{hour:02d}:{minute:02d} UTC"

        conf_band = {
            "p10": fmt_utc(p10_h),
            "p50": fmt_utc(p50_h),
            "p90": fmt_utc(p90_h),
        }

        # 6. Quayside Crane Handling Duration Modification
        if fixed_service_hours is not None and fixed_service_hours > 0:
            nominal_dock_h = float(fixed_service_hours)
        else:
            nominal_dock_h = service_time_hours(vessel_type, cargo_units, cranes_assigned)

        # Wind derating on quay cranes
        wind_spd = weather.wind_speed_knots
        if wind_spd <= 20.0:
            crane_wind_factor = 1.0
        elif wind_spd <= 35.0:
            crane_wind_factor = max(0.50, 1.0 - (wind_spd - 20.0) * 0.018)
        elif wind_spd <= 45.0:
            crane_wind_factor = 0.40  # severe wind surge delay
        else:
            crane_wind_factor = 0.15  # Emergency safety shutdown, near standstill

        # Mooring line surge penalty in berths due to high swell
        swell_penalty = 0.15 if hs > 1.8 else 0.0

        crane_health = max(0.2, min(1.0, port_cond.crane_health_pct / 100.0))
        net_crane_productivity = max(0.15, crane_wind_factor * crane_health)

        adjusted_handling_h = (nominal_dock_h - MOORING_OVERHEAD_H) / net_crane_productivity
        adjusted_overhead_h = MOORING_OVERHEAD_H * (1.0 + swell_penalty)
        predicted_dock_h = round(adjusted_overhead_h + adjusted_handling_h, 2)
        dock_delta_h = round(predicted_dock_h - nominal_dock_h, 2)

        derating_pct = round((1.0 - net_crane_productivity) * 100.0, 1)
        audit_log.append(
            f"Quayside Operations: Wind {wind_spd:.1f} kn derates crane handling by {derating_pct:.1f}%. "
            f"Dock duration: {nominal_dock_h:.1f}h -> {predicted_dock_h:.1f}h (delta: +{dock_delta_h:.1f}h)."
        )

        predicted_etd_h = round(predicted_arrival_hours + predicted_dock_h, 2)

        return PhysicsPredictionResult(
            original_eta_hours=round(nominal_eta_hours, 2),
            predicted_eta_hours=predicted_arrival_hours,
            eta_delta_minutes=eta_delta_minutes,
            eta_confidence_band=conf_band,
            nominal_dock_duration_hours=round(nominal_dock_h, 2),
            predicted_dock_duration_hours=predicted_dock_h,
            dock_duration_delta_hours=dock_delta_h,
            predicted_etd_hours=predicted_etd_h,
            distance_remaining_nmi=dist_nmi,
            nominal_speed_knots=v_nom,
            effective_sog_knots=round(sog_predicted, 2),
            speed_loss_knots=round(actual_loss, 2),
            speed_loss_pct=round(loss_pct, 1),
            headwind_speed_knots=round(headwind_knots, 1),
            wind_drag_speed_loss_knots=round(wind_speed_loss, 2),
            wave_resistance_speed_loss_knots=round(wave_speed_loss, 2),
            visibility_safety_cap_knots=visibility_cap,
            crane_weather_derating_pct=derating_pct,
            physics_audit_log=audit_log,
        )
