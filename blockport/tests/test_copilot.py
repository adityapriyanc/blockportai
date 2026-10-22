"""Tests for Explainable AI Port Copilot and Governance Workflow
(report §5.7, §7.3, §3 Objective 7).

Verifies:
1. Explainable recommendation generation grounded in Section 7 benchmark
2. Verification of physical constraints (LOA, depth, cranes) in recommendation card
3. Human-in-the-loop lifecycle: approve, modify, reject
4. Cryptographic blockchain anchoring of operator governance decisions
"""
import pytest

from blockport.blockchain.ledger import BlockPortLedger
from blockport.copilot.generator import PortCopilot
from blockport.copilot.workflow import GovernanceWorkflow
from blockport.optimizer.optimizer import BerthOptimizer
from blockport.twin.model import TwinVessel
from blockport.twin.scenarios import section7_case


def test_copilot_generates_section_7_recommendation():
    s7 = section7_case()
    baseline_vessels = s7["vessels"]
    reassignment_candidates = [
        s7["vessels"][0],
        s7["vessels"][1],
        TwinVessel(
            id=3,
            name="MV Delayed",
            vessel_type=s7["vessels"][2].vessel_type,
            loa_m=300,
            draft_m=12,
            cargo_units=960,
            arrival=s7["vessels"][2].arrival,
            allowed_berths=frozenset({"A1", "A2", "B1"}),
        ),
    ]
    berths = s7["berths"]

    opt = BerthOptimizer()
    opt_res = opt.optimize(
        reassignment_candidates, berths, baseline_vessels=baseline_vessels
    )

    copilot = PortCopilot()
    rec = copilot.generate_recommendation(
        recommendation_id=101,
        opt_result=opt_res,
        vessels=reassignment_candidates,
        berths=berths,
        eta_confidence_band={"p10": "-15m", "p50": "+0m", "p90": "+25m"},
    )

    assert rec.id == 101
    assert rec.status == "PENDING"
    assert rec.confidence_score >= 0.80

    # Section 7 benchmark impact verification
    assert rec.impact.wait_time_saved_hours >= 1.0
    assert rec.impact.cost_saved_usd >= 1000.0
    assert rec.impact.co2_saved_kg > 0

    # Actions list should include berth assignment / coordination
    assert len(rec.actions) > 0
    assert any("B1" in a.description or "Terminal B" in a.description for a in rec.actions)

    # Constraints verified
    assert len(rec.constraints_verified) > 0
    assert any("LOA clearance" in c for c in rec.constraints_verified)

    # Dictionary serialization
    d = rec.to_dict()
    assert d["status"] == "PENDING"
    assert "actions" in d
    assert "tradeoff_narrative" in d


def test_copilot_governance_approve_flow():
    ledger = BlockPortLedger()
    workflow = GovernanceWorkflow(ledger=ledger)

    s7 = section7_case()
    opt_res = BerthOptimizer().optimize(s7["vessels"], s7["berths"])
    copilot = PortCopilot()
    rec = copilot.generate_recommendation(
        recommendation_id=201,
        opt_result=opt_res,
        vessels=s7["vessels"],
        berths=s7["berths"],
    )

    workflow.register_recommendation(rec)
    assert workflow.get_recommendation(201).status == "PENDING"

    decision = workflow.approve(
        rec_id=201,
        operator="harbor_master_john",
        notes="Approved for Berth B1 redirection as weather is clear.",
    )

    assert decision.decision == "APPROVED"
    assert decision.operator == "harbor_master_john"
    assert decision.blockchain_tx_hash is not None
    assert rec.status == "APPROVED"

    # Verify blockchain recorded the decision
    tx = ledger.get_by_tx_hash(decision.blockchain_tx_hash)
    assert tx is not None
    assert tx.record_type == "APPROVE_PLAN"
    assert tx.operator == "harbor_master_john"

    # Second approval attempt should raise ValueError
    with pytest.raises(ValueError, match="already in state 'APPROVED'"):
        workflow.approve(201, operator="another_operator")


def test_copilot_governance_modify_flow():
    ledger = BlockPortLedger()
    workflow = GovernanceWorkflow(ledger=ledger)

    s7 = section7_case()
    opt_res = BerthOptimizer().optimize(s7["vessels"], s7["berths"])
    copilot = PortCopilot()
    rec = copilot.generate_recommendation(
        recommendation_id=202,
        opt_result=opt_res,
        vessels=s7["vessels"],
        berths=s7["berths"],
    )

    workflow.register_recommendation(rec)

    # Must provide reason
    with pytest.raises(ValueError, match="require explicit justification"):
        workflow.modify(
            rec_id=202,
            operator="planner_alice",
            modifications={"assigned_cranes": 2},
            reason="",
        )

    decision = workflow.modify(
        rec_id=202,
        operator="planner_alice",
        modifications={"assigned_cranes": 2},
        reason="Crane 3 under preventive maintenance, reducing gang to 2 cranes.",
    )

    assert decision.decision == "MODIFIED"
    assert rec.status == "MODIFIED"
    assert decision.modifications == {"assigned_cranes": 2}
    assert decision.blockchain_tx_hash is not None


def test_copilot_governance_reject_flow():
    ledger = BlockPortLedger()
    workflow = GovernanceWorkflow(ledger=ledger)

    s7 = section7_case()
    opt_res = BerthOptimizer().optimize(s7["vessels"], s7["berths"])
    copilot = PortCopilot()
    rec = copilot.generate_recommendation(
        recommendation_id=203,
        opt_result=opt_res,
        vessels=s7["vessels"],
        berths=s7["berths"],
    )

    workflow.register_recommendation(rec)

    decision = workflow.reject(
        rec_id=203,
        operator="port_director_bob",
        reason="Shipper contract stipulates dedicated terminal A priority.",
    )

    assert decision.decision == "REJECTED"
    assert rec.status == "REJECTED"
    assert decision.blockchain_tx_hash is not None

    valid_chain, _ = ledger.verify_chain_integrity()
    assert valid_chain is True
