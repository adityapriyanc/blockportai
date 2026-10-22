"""Trade-off analysis between Time, Cost, and Sustainability (report §5.5, §8.4 Obs. 2).

Disentangles the myth that every operational acceleration automatically cuts emissions:
Exposes explicit trade-offs and conflicts when minimizing wait time (T), minimizing costs (C),
and reducing emissions (E) diverge.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..optimizer.cost_model import CostModel
from ..twin.results import SimResult
from .estimator import GreenPortIntelligence


@dataclass(frozen=True)
class OperationalTradeoff:
    scenario_label: str
    time_delta_h: float            # negative = faster (time saved)
    cost_delta_usd: float          # negative = cheaper
    emissions_delta_kg: float      # negative = cleaner
    emissions_intensity_delta_pct: float
    conflict_detected: bool
    explanation: str
    underlying_assumptions: List[str]


def evaluate_tradeoffs(
    baseline_result: SimResult,
    candidate_result: SimResult,
    candidate_label: str = "Proposed Alternative",
    green_engine: Optional[GreenPortIntelligence] = None,
    cost_model: Optional[CostModel] = None,
) -> OperationalTradeoff:
    """Analyze trade-offs between two operational scenarios."""
    engine = green_engine or GreenPortIntelligence()
    cm = cost_model or CostModel()

    base_kpi = baseline_result.kpis()
    cand_kpi = candidate_result.kpis()

    time_delta = cand_kpi["total_wait_h"] - base_kpi["total_wait_h"]

    base_cost = cm.evaluate(baseline_result).C
    cand_cost = cm.evaluate(candidate_result).C
    cost_delta = cand_cost - base_cost

    base_emiss = engine.calculate(baseline_result)
    cand_emiss = engine.calculate(candidate_result)

    emiss_delta = (
        cand_emiss.breakdown.total_co2_kg - base_emiss.breakdown.total_co2_kg
    )
    base_int = base_emiss.breakdown.emissions_per_cargo_unit
    cand_int = cand_emiss.breakdown.emissions_per_cargo_unit
    intensity_delta_pct = (
        0.0 if base_int == 0 else 100.0 * (cand_int - base_int) / base_int
    )
    # Detect conflicts: e.g. time saved but emissions increased,
    # or cost saved but emissions increased
    conflict = False
    reasons: List[str] = []

    if time_delta < 0 and emiss_delta > 0:
        conflict = True
        reasons.append(
            f"Vessel waiting time reduced by {abs(time_delta):.1f}h, but emissions increased by "
            f"{emiss_delta:.1f} kg CO2 due to longer landside drayage or higher crane usage."
        )
    elif time_delta > 0 and emiss_delta < 0:
        conflict = True
        reasons.append(
            f"Emissions dropped by {abs(emiss_delta):.1f} kg CO2 despite {time_delta:.1f}h higher "
            f"waiting time (e.g., lower peak crane power or shorter hinterland truck routes)."
        )
    elif cost_delta < 0 and emiss_delta > 0:
        conflict = True
        reasons.append("Operating costs decreased, but environmental emissions increased.")
    elif cost_delta > 0 and emiss_delta < 0:
        conflict = True
        reasons.append(
            f"Emissions reduced by {abs(emiss_delta):.1f} kg CO2, but incurred ${cost_delta:.2f} "
            f"additional handling/drayage operating costs."
        )
    else:
        reasons.append(
            f"Decision aligned across metrics: time delta {time_delta:.1f}h, "
            f"cost delta ${cost_delta:.2f}, emissions delta {emiss_delta:.1f} kg CO2."
        )

    assumptions = [
        "Vessel auxiliary engines consume MDO at average hoteling and anchorage rates.",
        (
            f"Shore electric power emissions reflect regional grid factor "
            f"({engine.factors.grid_kg_co2_per_kwh:.3f} kg CO2/kWh)."
        ),
        "Truck drayage calculations assume average 1.6 TEU/truck and direct route mileage.",
        "Zero-emission shore power is not enabled unless cold-ironing infrastructure is verified.",
    ]

    return OperationalTradeoff(
        scenario_label=candidate_label,
        time_delta_h=time_delta,
        cost_delta_usd=cost_delta,
        emissions_delta_kg=emiss_delta,
        emissions_intensity_delta_pct=intensity_delta_pct,
        conflict_detected=conflict,
        explanation="; ".join(reasons),
        underlying_assumptions=assumptions,
    )
