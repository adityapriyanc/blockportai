"""Closed-Loop Feedback and Performance Tracking (report §5.8).

Monitors operational execution against predictive and optimized plans:
- Compares predicted ETA vs actual arrival (tracking MAE and signed bias)
- Compares scheduled wait time vs actual wait time
- Compares modeled fuel/emissions vs observed consumption
- Feeds residual metrics into the continuous learning and retraining engine
"""
from __future__ import annotations

import datetime
import math
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class ExecutionObservation:
    port_call_id: int
    vessel_id: int
    predicted_eta: datetime.datetime
    actual_arrival: datetime.datetime
    eta_error_minutes: float  # (actual - predicted) in minutes
    predicted_wait_h: float
    actual_wait_h: float
    wait_error_h: float       # (actual - predicted) in hours
    estimated_co2_kg: float
    actual_co2_kg: float
    co2_error_kg: float
    operator_decision: str    # APPROVED | MODIFIED | REJECTED | DEFAULT
    recorded_at: datetime.datetime


@dataclass(frozen=True)
class ResidualPerformanceSummary:
    total_observations: int
    eta_mae_minutes: float
    eta_rmse_minutes: float
    eta_bias_minutes: float
    wait_time_mae_hours: float
    co2_mae_kg: float
    eta_target_met: bool      # MAE < 30 min (report §3 obj 1)
    needs_retraining: bool
    summary: str


class ExecutionFeedbackTracker:
    """Collects post-voyage execution data and tracks predictive residuals."""

    def __init__(self, drift_threshold_mae_minutes: float = 25.0):
        self.drift_threshold_mae_minutes = drift_threshold_mae_minutes
        self.observations: List[ExecutionObservation] = []

    def record_execution(
        self,
        port_call_id: int,
        vessel_id: int,
        predicted_eta: datetime.datetime,
        actual_arrival: datetime.datetime,
        predicted_wait_h: float,
        actual_wait_h: float,
        estimated_co2_kg: float,
        actual_co2_kg: float,
        operator_decision: str = "APPROVED",
        recorded_at: Optional[datetime.datetime] = None,
    ) -> ExecutionObservation:
        """Record an executed port call observation."""
        now = recorded_at or datetime.datetime.now(datetime.timezone.utc)
        eta_err_min = (actual_arrival - predicted_eta).total_seconds() / 60.0
        wait_err_h = actual_wait_h - predicted_wait_h
        co2_err = actual_co2_kg - estimated_co2_kg

        obs = ExecutionObservation(
            port_call_id=port_call_id,
            vessel_id=vessel_id,
            predicted_eta=predicted_eta,
            actual_arrival=actual_arrival,
            eta_error_minutes=eta_err_min,
            predicted_wait_h=predicted_wait_h,
            actual_wait_h=actual_wait_h,
            wait_error_h=wait_err_h,
            estimated_co2_kg=estimated_co2_kg,
            actual_co2_kg=actual_co2_kg,
            co2_error_kg=co2_err,
            operator_decision=operator_decision,
            recorded_at=now,
        )
        self.observations.append(obs)
        return obs

    def evaluate_residuals(
        self,
        window_size: Optional[int] = None,
    ) -> ResidualPerformanceSummary:
        """Calculate performance metrics over the recent observation window."""
        subset = self.observations[-window_size:] if window_size else self.observations
        if not subset:
            return ResidualPerformanceSummary(
                total_observations=0,
                eta_mae_minutes=0.0,
                eta_rmse_minutes=0.0,
                eta_bias_minutes=0.0,
                wait_time_mae_hours=0.0,
                co2_mae_kg=0.0,
                eta_target_met=True,
                needs_retraining=False,
                summary="No execution observations recorded yet.",
            )

        n = len(subset)
        abs_eta_errs = [abs(o.eta_error_minutes) for o in subset]
        sq_eta_errs = [o.eta_error_minutes ** 2 for o in subset]
        signed_eta_errs = [o.eta_error_minutes for o in subset]
        abs_wait_errs = [abs(o.wait_error_h) for o in subset]
        abs_co2_errs = [abs(o.co2_error_kg) for o in subset]

        mae_eta = sum(abs_eta_errs) / n
        rmse_eta = math.sqrt(sum(sq_eta_errs) / n)
        bias_eta = sum(signed_eta_errs) / n
        mae_wait = sum(abs_wait_errs) / n
        mae_co2 = sum(abs_co2_errs) / n

        target_met = mae_eta < 30.0  # Report §3 Objective 1 target
        needs_retrain = mae_eta >= self.drift_threshold_mae_minutes

        summary = (
            f"Residual Feedback (n={n}): ETA MAE {mae_eta:.1f}m (Target <30m: {target_met}), "
            f"ETA RMSE {rmse_eta:.1f}m, Bias {bias_eta:+.1f}m; "
            f"Wait MAE {mae_wait:.2f}h; CO2 MAE {mae_co2:.1f}kg. "
            f"Retraining Needed: {needs_retrain}."
        )

        return ResidualPerformanceSummary(
            total_observations=n,
            eta_mae_minutes=round(mae_eta, 2),
            eta_rmse_minutes=round(rmse_eta, 2),
            eta_bias_minutes=round(bias_eta, 2),
            wait_time_mae_hours=round(mae_wait, 2),
            co2_mae_kg=round(mae_co2, 2),
            eta_target_met=target_met,
            needs_retraining=needs_retrain,
            summary=summary,
        )
