"""Pareto sensitivity and weight justification analysis (report §5.4, §8.4 Obs. 2).

Explores multi-objective trade-offs by varying weights alpha (time), beta (cost), gamma (emissions)
to establish the Pareto frontier and justify operational weight selections.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

from ..config import ObjectiveWeights
from ..twin.model import Outage, TwinBerth, TwinVessel
from .cost_model import ObjectiveComponents
from .optimizer import BerthOptimizer


@dataclass(frozen=True)
class ParetoPoint:
    label: str
    weights: ObjectiveWeights
    objective: ObjectiveComponents
    waiting_reduction_pct: float
    emissions_reduction_pct: float
    cost_reduction_pct: float


def sensitivity_analysis(
    vessels: Sequence[TwinVessel],
    berths: Sequence[TwinBerth],
    outages: Sequence[Outage] = (),
) -> List[ParetoPoint]:
    """Sweep weight profiles to demonstrate trade-offs across time, cost, and emissions."""
    profiles: List[Tuple[str, ObjectiveWeights]] = [
        ("balanced_default", ObjectiveWeights(alpha=1.0, beta=0.001, gamma=0.01)),
        ("time_focused", ObjectiveWeights(alpha=1.0, beta=0.0, gamma=0.0)),
        ("cost_focused", ObjectiveWeights(alpha=0.0, beta=1.0, gamma=0.0)),
        ("green_focused", ObjectiveWeights(alpha=0.0, beta=0.0, gamma=1.0)),
        ("time_green_hybrid", ObjectiveWeights(alpha=1.0, beta=0.0, gamma=0.02)),
    ]

    points: List[ParetoPoint] = []

    for label, weights in profiles:
        opt = BerthOptimizer(weights=weights, max_iterations=80)
        res = opt.optimize(vessels, berths, outages)
        points.append(
            ParetoPoint(
                label=label,
                weights=weights,
                objective=res.objective,
                waiting_reduction_pct=res.waiting_time_reduction_pct,
                emissions_reduction_pct=res.emissions_reduction_pct,
                cost_reduction_pct=res.cost_reduction_pct,
            )
        )

    return points
