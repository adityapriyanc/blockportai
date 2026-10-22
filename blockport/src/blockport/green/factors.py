"""Documented emission factors and fuel consumption coefficients (report §5.5, §8.4 Obs. 2).

Sources and Standards:
1. Marine Fuel Emission Factors:
   - Heavy Fuel Oil (HFO): 3.114 kg CO2 / kg fuel [IMO MEPC.308(73), Fourth IMO GHG Study 2020].
   - Marine Diesel / Gas Oil (MDO/MGO): 3.206 kg CO2 / kg fuel [IMO MEPC.308(73)].
   - Liquefied Natural Gas (LNG): 2.750 kg CO2 / kg fuel [IMO 2020].
2. Electricity Grid Factor:
   - Regional grid default: 0.45 kg CO2 / kWh (clean mix proxy; configurable per port).
3. Road Truck Drayage:
   - Ultra-low sulfur diesel: 2.68 kg CO2 / litre [IPCC 2006 Guidelines].
   - Average drayage consumption: 0.35 litres / mile (approx. 7.5 mpg).
   - Gate / queue idling consumption: 2.5 litres / hour.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from ..models import VesselType


@dataclass(frozen=True)
class VesselAuxiliaryProfile:
    vessel_type: VesselType
    fuel_kind: str  # mdo, hfo, lng
    aux_fuel_anchorage_kg_per_h: float  # waiting at anchor (idling load)
    aux_fuel_berth_kg_per_h: float      # hoteling at berth without shore power
    hoteling_kw_shore_power: float      # electrical load if cold-ironing (shore power) connected


VESSEL_PROFILES: Dict[VesselType, VesselAuxiliaryProfile] = {
    VesselType.CONTAINER: VesselAuxiliaryProfile(
        vessel_type=VesselType.CONTAINER,
        fuel_kind="mdo",
        aux_fuel_anchorage_kg_per_h=180.0,
        aux_fuel_berth_kg_per_h=220.0,
        hoteling_kw_shore_power=800.0,
    ),
    VesselType.BULK: VesselAuxiliaryProfile(
        vessel_type=VesselType.BULK,
        fuel_kind="mdo",
        aux_fuel_anchorage_kg_per_h=100.0,
        aux_fuel_berth_kg_per_h=120.0,
        hoteling_kw_shore_power=450.0,
    ),
    VesselType.TANKER: VesselAuxiliaryProfile(
        vessel_type=VesselType.TANKER,
        fuel_kind="mdo",
        aux_fuel_anchorage_kg_per_h=200.0,
        aux_fuel_berth_kg_per_h=260.0,
        hoteling_kw_shore_power=950.0,
    ),
    VesselType.LNG: VesselAuxiliaryProfile(
        vessel_type=VesselType.LNG,
        fuel_kind="lng",
        aux_fuel_anchorage_kg_per_h=190.0,
        aux_fuel_berth_kg_per_h=210.0,
        hoteling_kw_shore_power=850.0,
    ),
}


@dataclass(frozen=True)
class EmissionFactorsDocumentation:
    hfo_kg_co2_per_kg: float = 3.114
    mdo_kg_co2_per_kg: float = 3.206
    lng_kg_co2_per_kg: float = 2.750
    grid_kg_co2_per_kwh: float = 0.350
    truck_diesel_kg_co2_per_litre: float = 2.680
    truck_litres_per_mile: float = 0.350
    truck_idle_litres_per_hour: float = 2.500
    crane_kw_average: float = 400.0
    sources: Dict[str, str] = field(
        default_factory=lambda: {
            "mdo_kg_co2_per_kg": "IMO MEPC.308(73) Resolution",
            "hfo_kg_co2_per_kg": "IMO MEPC.308(73) Resolution",
            "lng_kg_co2_per_kg": "IMO 2020 Fourth GHG Study",
            "grid_kg_co2_per_kwh": "Regional Grid Carbon Intensity Factor",
            "truck_diesel_kg_co2_per_litre": "EPA SmartWay / IPCC 2006 Guidelines",
            "truck_litres_per_mile": "EPA SmartWay Drayage Fleet Average",
            "truck_idle_litres_per_hour": "EPA Technical Report on Heavy-Duty Idling",
            "crane_kw_average": "Port Equipment Electrification Profile",
        }
    )


DEFAULT_EMISSION_FACTORS = EmissionFactorsDocumentation()
