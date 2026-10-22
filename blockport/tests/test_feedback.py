"""Tests for Closed-Loop Feedback and Adaptive Learning (report §5.8).

Verifies:
1. Execution residual tracking (ETA MAE, bias, wait time, CO2)
2. Concept drift detection (Page-Hinkley test) flagging retraining
3. Operator preference learning and adaptive optimizer weights
"""
from datetime import datetime, timedelta, timezone

from blockport.config import ObjectiveWeights
from blockport.feedback.drift import ConceptDriftDetector
from blockport.feedback.preferences import OperatorPreferenceLearner
from blockport.feedback.tracker import ExecutionFeedbackTracker


def test_execution_feedback_tracker():
    tracker = ExecutionFeedbackTracker(drift_threshold_mae_minutes=25.0)

    t0 = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)

    # Record 10 simulated executions with small errors (~10 min error)
    for i in range(10):
        tracker.record_execution(
            port_call_id=i + 1,
            vessel_id=i + 1,
            predicted_eta=t0 + timedelta(hours=i),
            actual_arrival=t0 + timedelta(hours=i, minutes=10 if i % 2 == 0 else -10),
            predicted_wait_h=1.0,
            actual_wait_h=1.2,
            estimated_co2_kg=25000.0,
            actual_co2_kg=25200.0,
            operator_decision="APPROVED",
        )

    summary = tracker.evaluate_residuals()
    assert summary.total_observations == 10
    assert summary.eta_mae_minutes == 10.0
    assert summary.eta_target_met is True  # < 30m target met
    assert summary.needs_retraining is False


def test_concept_drift_detector_stable_vs_shift():
    detector = ConceptDriftDetector(threshold=30.0, delta=2.0, min_samples=10)

    # 1. Stable errors centered around 0
    stable_errors = [-5.0, 4.0, -2.0, 3.0, -1.0, 2.0, -4.0, 3.0, -2.0, 1.0, -3.0, 2.0]
    sig_stable = detector.check_residuals(stable_errors)
    assert sig_stable.drift_detected is False
    assert sig_stable.drift_type == "NONE"

    # 2. Systematic shift: vessels arriving 45-60 min late
    shifted_errors = [45.0, 50.0, 55.0, 60.0, 48.0, 52.0, 58.0, 62.0, 50.0, 55.0, 58.0]
    sig_shift = detector.check_residuals(shifted_errors)
    assert sig_shift.drift_detected is True
    assert sig_shift.drift_type == "MEAN_SHIFT"
    assert "Triggering automated" in sig_shift.recommendation


def test_operator_preference_learning():
    learner = OperatorPreferenceLearner()
    base_weights = ObjectiveWeights(alpha=1.0, beta=0.001, gamma=0.01)

    # Log several approvals
    learner.log_operator_action(1, "APPROVED", "Plan optimal", "Berth:A1")
    assert learner.get_berth_penalty("A1") == 1.0

    # Operator repeatedly rejects Berth B2 due to recurring shore crane issues
    learner.log_operator_action(
        2, "REJECTED", "Crane 2 hydraulic fault, severe delays", "Berth:B2"
    )
    learner.log_operator_action(
        3, "REJECTED", "Avoid Berth B2 until maintenance complete", "Berth:B2"
    )

    penalty = learner.get_berth_penalty("B2")
    assert penalty > 1.0  # Berth B2 gets penalized

    # Rejection citing carbon emissions adapts gamma weight
    learner.log_operator_action(
        4, "REJECTED", "Excessive carbon emissions from long truck routes", "Terminal:Terminal A"
    )
    adapted = learner.adapt_objective_weights(base_weights)
    assert adapted.gamma > base_weights.gamma
    assert adapted.alpha > base_weights.alpha
