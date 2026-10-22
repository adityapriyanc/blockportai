"""Human-in-the-Loop Governance workflow engine (report §5.7, §3 Objective 7).

Implements the operator review lifecycle:
- approve: accepts recommended plan, commits to execution, anchors to blockchain.
- modify: captures operator adjustments with justification, validates constraints, anchors.
- reject: records rejection rationale into audit feedback loop, anchors.
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

from ..blockchain.canonical import hash_record
from ..blockchain.ledger import BlockPortLedger
from ..models import Approval, Recommendation, RecommendationStatus
from .models import CopilotRecommendation, ReviewDecision


class GovernanceWorkflow:
    """Manages human operator decision-making and cryptographic blockchain anchoring."""

    def __init__(self, ledger: Optional[BlockPortLedger] = None):
        self.ledger = ledger or BlockPortLedger()
        self._recommendations: Dict[int, CopilotRecommendation] = {}
        self._decisions: Dict[int, ReviewDecision] = {}

    def register_recommendation(
        self,
        rec: CopilotRecommendation,
        db_session: Optional[Any] = None,
    ) -> None:
        """Register a new AI-generated recommendation for operator review."""
        self._recommendations[rec.id] = rec

        if db_session is not None:
            db_rec = Recommendation(
                id=rec.id,
                plan=rec.to_dict(),
                metrics=rec.impact.to_dict(),
                explanation=rec.rationale,
                status=RecommendationStatus.PENDING,
            )
            db_session.add(db_rec)

    def get_recommendation(self, rec_id: int) -> Optional[CopilotRecommendation]:
        return self._recommendations.get(rec_id)

    def get_decision(self, rec_id: int) -> Optional[ReviewDecision]:
        return self._decisions.get(rec_id)

    def approve(
        self,
        rec_id: int,
        operator: str,
        notes: Optional[str] = None,
        db_session: Optional[Any] = None,
    ) -> ReviewDecision:
        """Operator approves recommendation without changes."""
        rec = self._recommendations.get(rec_id)
        if rec is None:
            raise KeyError(f"Recommendation {rec_id} not found")
        if rec.status != "PENDING":
            raise ValueError(f"Recommendation {rec_id} is already in state '{rec.status}'")

        now = datetime.datetime.now(datetime.timezone.utc)
        rec.status = "APPROVED"

        # Anchor on-chain
        payload = {
            "recommendation_id": rec_id,
            "decision": "APPROVED",
            "operator": operator,
            "notes": notes or "",
            "timestamp": now.isoformat(),
        }
        rec_hash = hash_record("APPROVE_PLAN", payload)
        tx = self.ledger.anchor_record(
            record_type="APPROVE_PLAN",
            subject_table="recommendations",
            subject_id=rec_id,
            record_hash=rec_hash,
            operator=operator,
            timestamp=now,
            db_session=db_session,
        )

        decision = ReviewDecision(
            recommendation_id=rec_id,
            operator=operator,
            decision="APPROVED",
            reason=notes,
            decided_at=now,
            blockchain_tx_hash=tx.tx_hash,
        )
        self._decisions[rec_id] = decision

        if db_session is not None:
            db_app = Approval(
                recommendation_id=rec_id,
                operator=operator,
                decision=RecommendationStatus.APPROVED,
                reason=notes,
                decided_at=now,
            )
            db_session.add(db_app)

        return decision

    def modify(
        self,
        rec_id: int,
        operator: str,
        modifications: Dict[str, Any],
        reason: str,
        db_session: Optional[Any] = None,
    ) -> ReviewDecision:
        """Operator approves recommendation with operational modifications."""
        rec = self._recommendations.get(rec_id)
        if rec is None:
            raise KeyError(f"Recommendation {rec_id} not found")
        if rec.status != "PENDING":
            raise ValueError(f"Recommendation {rec_id} is already in state '{rec.status}'")
        if not reason.strip():
            raise ValueError("Modifications require explicit justification notes")

        now = datetime.datetime.now(datetime.timezone.utc)
        rec.status = "MODIFIED"

        payload = {
            "recommendation_id": rec_id,
            "decision": "MODIFIED",
            "operator": operator,
            "reason": reason,
            "modifications": modifications,
            "timestamp": now.isoformat(),
        }
        rec_hash = hash_record("MODIFY_PLAN", payload)
        tx = self.ledger.anchor_record(
            record_type="MODIFY_PLAN",
            subject_table="recommendations",
            subject_id=rec_id,
            record_hash=rec_hash,
            operator=operator,
            timestamp=now,
            db_session=db_session,
        )

        decision = ReviewDecision(
            recommendation_id=rec_id,
            operator=operator,
            decision="MODIFIED",
            reason=reason,
            decided_at=now,
            modifications=modifications,
            blockchain_tx_hash=tx.tx_hash,
        )
        self._decisions[rec_id] = decision

        if db_session is not None:
            db_app = Approval(
                recommendation_id=rec_id,
                operator=operator,
                decision=RecommendationStatus.MODIFIED,
                reason=reason,
                decided_at=now,
                modified_plan=modifications,
            )
            db_session.add(db_app)

        return decision

    def reject(
        self,
        rec_id: int,
        operator: str,
        reason: str,
        db_session: Optional[Any] = None,
    ) -> ReviewDecision:
        """Operator rejects recommendation, reverting to default or baseline plan."""
        rec = self._recommendations.get(rec_id)
        if rec is None:
            raise KeyError(f"Recommendation {rec_id} not found")
        if rec.status != "PENDING":
            raise ValueError(f"Recommendation {rec_id} is already in state '{rec.status}'")
        if not reason.strip():
            raise ValueError("Rejection requires explicit operator reasoning for learning loop")

        now = datetime.datetime.now(datetime.timezone.utc)
        rec.status = "REJECTED"

        payload = {
            "recommendation_id": rec_id,
            "decision": "REJECTED",
            "operator": operator,
            "reason": reason,
            "timestamp": now.isoformat(),
        }
        rec_hash = hash_record("REJECT_PLAN", payload)
        tx = self.ledger.anchor_record(
            record_type="REJECT_PLAN",
            subject_table="recommendations",
            subject_id=rec_id,
            record_hash=rec_hash,
            operator=operator,
            timestamp=now,
            db_session=db_session,
        )

        decision = ReviewDecision(
            recommendation_id=rec_id,
            operator=operator,
            decision="REJECTED",
            reason=reason,
            decided_at=now,
            blockchain_tx_hash=tx.tx_hash,
        )
        self._decisions[rec_id] = decision

        if db_session is not None:
            db_app = Approval(
                recommendation_id=rec_id,
                operator=operator,
                decision=RecommendationStatus.REJECTED,
                reason=reason,
                decided_at=now,
            )
            db_session.add(db_app)

        return decision
