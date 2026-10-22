"""Operator Preference and Rejection Learning (report §5.8).

Analyzes Human-in-the-Loop decision patterns to adaptively tune optimizer penalty
parameters and reduce repeated operator rejections.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from ..config import ObjectiveWeights


@dataclass
class PreferenceFeedbackEntry:
    recommendation_id: int
    decision: str  # APPROVED | MODIFIED | REJECTED
    reason: str
    target_entity: str  # e.g., "Terminal:Terminal B" or "Berth:A1"


class OperatorPreferenceLearner:
    """Adapts optimizer objective preferences from human operator feedback."""

    def __init__(self):
        self.history: List[PreferenceFeedbackEntry] = []
        self.berth_rejection_counts: Dict[str, int] = {}
        self.terminal_rejection_counts: Dict[str, int] = {}

    def log_operator_action(
        self,
        recommendation_id: int,
        decision: str,
        reason: Optional[str] = None,
        target_entity: str = "general",
    ) -> None:
        entry = PreferenceFeedbackEntry(
            recommendation_id=recommendation_id,
            decision=decision,
            reason=reason or "",
            target_entity=target_entity,
        )
        self.history.append(entry)

        if decision == "REJECTED":
            if "Berth:" in target_entity:
                b_name = target_entity.split("Berth:")[1]
                self.berth_rejection_counts[b_name] = (
                    self.berth_rejection_counts.get(b_name, 0) + 1
                )
            elif "Terminal:" in target_entity:
                t_name = target_entity.split("Terminal:")[1]
                self.terminal_rejection_counts[t_name] = (
                    self.terminal_rejection_counts.get(t_name, 0) + 1
                )

    def get_berth_penalty(self, berth_name: str) -> float:
        """Returns penalty multiplier for berths that operators frequently reject."""
        rejections = self.berth_rejection_counts.get(berth_name, 0)
        return min(2.0, 1.0 + 0.15 * rejections)

    def adapt_objective_weights(
        self,
        base_weights: ObjectiveWeights,
    ) -> ObjectiveWeights:
        """Adjusts weights based on systemic operator rejections."""
        rejection_reasons = " ".join([
            e.reason.lower() for e in self.history if e.decision == "REJECTED"
        ])

        alpha_adj = base_weights.alpha
        beta_adj = base_weights.beta
        gamma_adj = base_weights.gamma

        if "emission" in rejection_reasons or "carbon" in rejection_reasons:
            gamma_adj *= 1.25  # place 25% higher weight on emissions
        if "delay" in rejection_reasons or "wait" in rejection_reasons:
            alpha_adj *= 1.25  # place 25% higher weight on wait time minimization

        return ObjectiveWeights(
            alpha=alpha_adj,
            beta=beta_adj,
            gamma=gamma_adj,
        )
