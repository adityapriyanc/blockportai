"""Cost, waiting time, and emissions model for multi-objective optimization (report §5.4).

Formulation:
    Minimize J = alpha * T + beta * C + gamma * E

where:
    T = Total vessel waiting time (hours)
    C = Direct operating cost (USD: vessel waiting demurrage, crane work, truck drayage)
    E = Estimated CO2 emissions (kg CO2: auxiliary engine idling, cranes, truck fuel)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from ..config import ObjectiveWeights, get_settings
from ..models import VesselType
from ..twin.results import SimResult

# Hourly charter/demurrage waiting cost in USD
CHARTER_WAIT_COST_PER_HOUR: Dict[VesselType, float] = {
    VesselType.CONTAINER: 1200.0,
    VesselType.BULK: 900.0,
    VesselType.TANKER: 1600.0,
    VesselType.LNG: 1800.0,
}

# Auxiliary engine fuel consumption at anchorage while waiting (kg fuel / hour)
AUX_ENGINE_FUEL_KG_PER_H: Dict[VesselType, float] = {
    VesselType.CONTAINER: 100.0,
    VesselType.BULK: 75.0,
    VesselType.TANKER: 120.0,
    VesselType.LNG: 130.0,
}

# Cost per crane hour (maintenance + base power, USD)
CRANE_COST_PER_HOUR = 120.0

# Truck drayage parameters (Terminal to inland intermodal depot / yard)
# Terminal B is 12 miles closer roundtrip to logistics hub than Terminal A (report §6.5/§7.3)
TRUCK_ROUNDTRIP_MILES: Dict[str, float] = {
    "Terminal A": 25.0,
    "Terminal B": 13.0,
}
TRUCK_COST_PER_MILE = 3.50  # USD per truck mile
TRUCK_DIESEL_LITRES_PER_MILE = 0.35  # L diesel / mile
TEU_PER_TRUCK = 1.6  # average containers carried per drayage trip


@dataclass(frozen=True)
class ObjectiveComponents:
    T: float  # hours of waiting time
    C: float  # USD operating cost
    E: float  # kg CO2 emissions
    J: float  # scalarized objective score

    # Detailed breakdowns
    vessel_demurrage_cost: float
    crane_operating_cost: float
    truck_drayage_cost: float
    aux_idling_emissions_kg: float
    crane_emissions_kg: float
    truck_emissions_kg: float


class CostModel:
    def __init__(self, weights: Optional[ObjectiveWeights] = None):
        cfg = get_settings()
        self.weights = weights or cfg.objective_weights
        self.emissions = cfg.emission_factors

    def evaluate(self, sim_result: SimResult) -> ObjectiveComponents:
        vessels = sim_result.vessels
        berths_by_name = {b.name: b for b in sim_result.berths}

        # 1. Total waiting time T (hours)
        total_wait_h = sum(r.wait_h for r in sim_result.records)
        # Unserved penalty if any vessel could not be accommodated
        unserved_penalty_h = len(sim_result.unserved) * 500.0
        T = total_wait_h + unserved_penalty_h

        # 2. Operating cost C (USD)
        demurrage_cost = 0.0
        aux_emissions_kg = 0.0
        fuel_factor = self.emissions.marine_diesel_kg_co2_per_kg_fuel

        for r in sim_result.records:
            v = vessels[r.vessel_id]
            wait_h = r.wait_h
            demurrage_cost += wait_h * CHARTER_WAIT_COST_PER_HOUR.get(v.vessel_type, 1000.0)
            aux_fuel = wait_h * AUX_ENGINE_FUEL_KG_PER_H.get(v.vessel_type, 100.0)
            aux_emissions_kg += aux_fuel * fuel_factor

        # Unserved penalty costs
        demurrage_cost += len(sim_result.unserved) * 50000.0

        # Crane cost and electricity emissions
        total_crane_hours = sum(r.cranes * r.service_h for r in sim_result.records
                                if vessels[r.vessel_id].vessel_type == VesselType.CONTAINER)
        crane_cost = total_crane_hours * CRANE_COST_PER_HOUR
        grid_factor = self.emissions.grid_electricity_kg_co2_per_kwh
        crane_emissions_kg = total_crane_hours * 400.0 * grid_factor

        # Truck drayage transport cost and emissions
        truck_cost = 0.0
        truck_emissions_kg = 0.0
        truck_diesel_factor = self.emissions.truck_diesel_kg_co2_per_litre

        for r in sim_result.records:
            v = vessels[r.vessel_id]
            if v.vessel_type == VesselType.CONTAINER:
                b = berths_by_name.get(r.berth)
                term = b.terminal if b else "Terminal A"
                miles_per_trip = TRUCK_ROUNDTRIP_MILES.get(term, 20.0)
                truck_trips = max(1, int(round(v.cargo_units / TEU_PER_TRUCK)))
                total_miles = truck_trips * miles_per_trip

                truck_cost += total_miles * TRUCK_COST_PER_MILE
                litres = total_miles * TRUCK_DIESEL_LITRES_PER_MILE
                truck_emissions_kg += litres * truck_diesel_factor

        C = demurrage_cost + crane_cost + truck_cost
        E = aux_emissions_kg + crane_emissions_kg + truck_emissions_kg

        # Multi-objective J = alpha*T + beta*C + gamma*E
        J = self.weights.alpha * T + self.weights.beta * C + self.weights.gamma * E

        return ObjectiveComponents(
            T=T,
            C=C,
            E=E,
            J=J,
            vessel_demurrage_cost=demurrage_cost,
            crane_operating_cost=crane_cost,
            truck_drayage_cost=truck_cost,
            aux_idling_emissions_kg=aux_emissions_kg,
            crane_emissions_kg=crane_emissions_kg,
            truck_emissions_kg=truck_emissions_kg,
        )

    def score(self, sim_result: SimResult) -> float:
        """Returns the scalarized J score."""
        return self.evaluate(sim_result).J
