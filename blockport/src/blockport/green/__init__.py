"""Layer 3c: Green Port Intelligence (report §5.5, §4.9, §4.16).

Quantifies and verifies environmental indicators:
- Auxiliary engine fuel consumption at anchorage (waiting time)
- Berth hoteling load (with optional shore power / cold ironing)
- Cargo handling equipment electricity (gantry cranes)
- Landside drayage truck transit & gate idling
- Target metric: Emissions per unit of cargo handled (kg CO2 / unit)
"""
from __future__ import annotations

from .estimator import EmissionBreakdown, EmissionReport, GreenPortIntelligence
from .factors import (
    DEFAULT_EMISSION_FACTORS,
    EmissionFactorsDocumentation,
    VesselAuxiliaryProfile,
)
from .tradeoffs import OperationalTradeoff, evaluate_tradeoffs

__all__ = [
    "GreenPortIntelligence",
    "EmissionReport",
    "EmissionBreakdown",
    "DEFAULT_EMISSION_FACTORS",
    "EmissionFactorsDocumentation",
    "VesselAuxiliaryProfile",
    "OperationalTradeoff",
    "evaluate_tradeoffs",
]
