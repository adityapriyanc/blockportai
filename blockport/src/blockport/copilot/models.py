"""Data models for Explainable AI Port Copilot (report §5.7, §7.3, §3 Objective 7)."""
from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ActionItem:
    action_type: str  # REASSIGN_BERTH | ADJUST_CRANES | SCHEDULE_TRUCKS | ALERT_CONGESTION
    entity_id: str    # e.g., "Vessel:3" or "Berth:B1"
    description: str


@dataclass(frozen=True)
class ImpactScorecard:
    wait_time_saved_hours: float
    cost_saved_usd: float
    co2_saved_kg: float
    emissions_intensity_delta_pct: float
    berth_utilization_pct: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "wait_time_saved_hours": round(self.wait_time_saved_hours, 2),
            "cost_saved_usd": round(self.cost_saved_usd, 2),
            "co2_saved_kg": round(self.co2_saved_kg, 2),
            "emissions_intensity_delta_pct": round(self.emissions_intensity_delta_pct, 2),
            "berth_utilization_pct": round(self.berth_utilization_pct, 2),
        }


@dataclass
class CopilotRecommendation:
    id: int
    title: str
    summary: str
    rationale: str
    confidence_score: float  # 0.0 - 1.0
    impact: ImpactScorecard
    actions: List[ActionItem]
    constraints_verified: List[str]
    tradeoff_narrative: str
    eta_confidence_band: Optional[Dict[str, str]] = None
    status: str = "PENDING"  # PENDING | APPROVED | MODIFIED | REJECTED
    created_at: datetime.datetime = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc)
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "rationale": self.rationale,
            "confidence_score": round(self.confidence_score, 3),
            "impact": self.impact.to_dict(),
            "actions": [asdict(a) for a in self.actions],
            "constraints_verified": self.constraints_verified,
            "tradeoff_narrative": self.tradeoff_narrative,
            "eta_confidence_band": self.eta_confidence_band,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class ReviewDecision:
    recommendation_id: int
    operator: str
    decision: str  # APPROVED | MODIFIED | REJECTED
    reason: Optional[str]
    decided_at: datetime.datetime
    modifications: Optional[Dict[str, Any]] = None
    blockchain_tx_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "operator": self.operator,
            "decision": self.decision,
            "reason": self.reason,
            "decided_at": self.decided_at.isoformat(),
            "modifications": self.modifications,
            "blockchain_tx_hash": self.blockchain_tx_hash,
        }
