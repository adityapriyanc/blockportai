"""Green Port Intelligence environmental accounting engine (report §5.5, §3 Objective 4).

Computes transparent, auditable carbon footprints across:
1. Anchorage waiting idling (avoidable emissions directly impacted by berth scheduling)
2. Berth hoteling power (auxiliary generator or optional cold-ironing shore power)
3. Cargo handling equipment (gantry cranes)
4. Landside drayage truck movements (route distance influenced by terminal choice)

Primary Key Performance Indicator (report §3 Objective 4):
    Emissions Intensity = Total CO2 (kg) / Total Cargo Handled (Units)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from ..models import VesselType
from ..twin.results import SimResult
from .factors import (
    DEFAULT_EMISSION_FACTORS,
    VESSEL_PROFILES,
    EmissionFactorsDocumentation,
)


@dataclass(frozen=True)
class EmissionBreakdown:
    anchorage_waiting_co2_kg: float
    berth_hoteling_co2_kg: float
    crane_handling_co2_kg: float
    truck_drayage_co2_kg: float
    total_co2_kg: float
    total_cargo_units: float
    emissions_per_cargo_unit: float  # kg CO2 / unit cargo (report §3 obj 4)


@dataclass(frozen=True)
class EmissionReport:
    breakdown: EmissionBreakdown
    fuel_consumed_kg: Dict[str, float]       # fuel_type -> kg
    electricity_kwh: float
    truck_diesel_litres: float
    energy_records: List[Dict[str, object]]  # serialized for database persistence


@dataclass(frozen=True)
class GreenComparison:
    baseline_intensity: float
    optimized_intensity: float
    reduction_pct: float
    total_co2_saved_kg: float
    met_target: bool  # >= 5% reduction per cargo unit (report §3 obj 4)
    explanation: str


class GreenPortIntelligence:
    def __init__(
        self,
        factors: Optional[EmissionFactorsDocumentation] = None,
        use_shore_power: bool = False,
    ):
        self.factors = factors or DEFAULT_EMISSION_FACTORS
        self.use_shore_power = use_shore_power

    def _fuel_factor(self, fuel_kind: str) -> float:
        if fuel_kind == "lng":
            return self.factors.lng_kg_co2_per_kg
        elif fuel_kind == "hfo":
            return self.factors.hfo_kg_co2_per_kg
        return self.factors.mdo_kg_co2_per_kg

    def calculate(self, sim_result: SimResult) -> EmissionReport:
        vessels = sim_result.vessels
        berths_by_name = {b.name: b for b in sim_result.berths}

        anchorage_co2 = 0.0
        hoteling_co2 = 0.0
        crane_co2 = 0.0
        truck_co2 = 0.0

        fuels_kg: Dict[str, float] = {"mdo": 0.0, "hfo": 0.0, "lng": 0.0}
        total_elec_kwh = 0.0
        total_truck_litres = 0.0
        total_cargo = 0.0

        energy_recs: List[Dict[str, object]] = []

        for r in sim_result.records:
            v = vessels[r.vessel_id]
            total_cargo += v.cargo_units
            prof = VESSEL_PROFILES.get(
                v.vessel_type, VESSEL_PROFILES[VesselType.CONTAINER]
            )
            ff = self._fuel_factor(prof.fuel_kind)

            # 1. Anchorage waiting emissions (avoidable delay)
            if r.wait_h > 0:
                wait_fuel_kg = r.wait_h * prof.aux_fuel_anchorage_kg_per_h
                fuels_kg[prof.fuel_kind] += wait_fuel_kg
                co2_wait = wait_fuel_kg * ff
                anchorage_co2 += co2_wait
                energy_recs.append({
                    "source": f"vessel_{v.id}_anchorage",
                    "kind": f"{prof.fuel_kind}_fuel_kg",
                    "quantity": wait_fuel_kg,
                    "recorded_at": r.arrival,
                    "port_call_id": v.id,
                })

            # 2. Berth hoteling emissions
            if self.use_shore_power:
                elec_kwh = r.service_h * prof.hoteling_kw_shore_power
                total_elec_kwh += elec_kwh
                hoteling_co2 += elec_kwh * self.factors.grid_kg_co2_per_kwh
                energy_recs.append({
                    "source": f"vessel_{v.id}_shore_power",
                    "kind": "electricity_kwh",
                    "quantity": elec_kwh,
                    "recorded_at": r.start,
                    "port_call_id": v.id,
                })
            else:
                berth_fuel_kg = r.service_h * prof.aux_fuel_berth_kg_per_h
                fuels_kg[prof.fuel_kind] += berth_fuel_kg
                co2_berth = berth_fuel_kg * ff
                hoteling_co2 += co2_berth
                energy_recs.append({
                    "source": f"vessel_{v.id}_berth_hotel",
                    "kind": f"{prof.fuel_kind}_fuel_kg",
                    "quantity": berth_fuel_kg,
                    "recorded_at": r.start,
                    "port_call_id": v.id,
                })

            # 3. Crane handling equipment (container vessels)
            if v.vessel_type == VesselType.CONTAINER:
                crane_hours = r.cranes * r.service_h
                crane_kwh = crane_hours * self.factors.crane_kw_average
                total_elec_kwh += crane_kwh
                co2_crane = crane_kwh * self.factors.grid_kg_co2_per_kwh
                crane_co2 += co2_crane
                energy_recs.append({
                    "source": f"berth_{r.berth}_cranes",
                    "kind": "electricity_kwh",
                    "quantity": crane_kwh,
                    "recorded_at": r.start,
                    "port_call_id": v.id,
                })

            # 4. Landside drayage trucks (container vessels)
            if v.vessel_type == VesselType.CONTAINER:
                berth_obj = berths_by_name.get(r.berth)
                term = berth_obj.terminal if berth_obj else "Terminal A"
                # Terminal B saves 12 miles roundtrip (report §6.5/§7.3)
                miles_trip = 13.0 if term == "Terminal B" else 25.0
                truck_trips = max(1, int(round(v.cargo_units / 1.6)))
                trip_litres = (
                    truck_trips * miles_trip * self.factors.truck_litres_per_mile
                )
                total_truck_litres += trip_litres
                co2_trucks = trip_litres * self.factors.truck_diesel_kg_co2_per_litre
                truck_co2 += co2_trucks
                energy_recs.append({
                    "source": f"drayage_trucks_{term}",
                    "kind": "diesel_litres",
                    "quantity": trip_litres,
                    "recorded_at": r.start,
                    "port_call_id": v.id,
                })

        total_co2 = anchorage_co2 + hoteling_co2 + crane_co2 + truck_co2
        intensity = total_co2 / max(total_cargo, 1.0)

        breakdown = EmissionBreakdown(
            anchorage_waiting_co2_kg=anchorage_co2,
            berth_hoteling_co2_kg=hoteling_co2,
            crane_handling_co2_kg=crane_co2,
            truck_drayage_co2_kg=truck_co2,
            total_co2_kg=total_co2,
            total_cargo_units=total_cargo,
            emissions_per_cargo_unit=intensity,
        )

        return EmissionReport(
            breakdown=breakdown,
            fuel_consumed_kg=fuels_kg,
            electricity_kwh=total_elec_kwh,
            truck_diesel_litres=total_truck_litres,
            energy_records=energy_recs,
        )

    def compare_to_baseline(
        self, baseline: SimResult, proposed: SimResult
    ) -> GreenComparison:
        """Compare proposed operational plan against defined baseline (report §3 obj 4)."""
        base_rep = self.calculate(baseline)
        prop_rep = self.calculate(proposed)

        base_int = base_rep.breakdown.emissions_per_cargo_unit
        prop_int = prop_rep.breakdown.emissions_per_cargo_unit

        red_pct = 0.0 if base_int == 0 else 100.0 * (base_int - prop_int) / base_int
        co2_saved = base_rep.breakdown.total_co2_kg - prop_rep.breakdown.total_co2_kg

        target_pct = 5.0  # Report §3 Objective 4 target: at least 5% reduction
        met = red_pct >= target_pct

        explanation = (
            f"Emissions intensity decreased from {base_int:.3f} to {prop_int:.3f} kg CO2/unit "
            f"({red_pct:.2f}% reduction, saving {co2_saved:.1f} kg CO2 total). "
            f"Anchorage waiting CO2 dropped from "
            f"{base_rep.breakdown.anchorage_waiting_co2_kg:.1f} kg to "
            f"{prop_rep.breakdown.anchorage_waiting_co2_kg:.1f} kg."
        )

        return GreenComparison(
            baseline_intensity=base_int,
            optimized_intensity=prop_int,
            reduction_pct=red_pct,
            total_co2_saved_kg=co2_saved,
            met_target=met,
            explanation=explanation,
        )
