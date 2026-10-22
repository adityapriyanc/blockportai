"""Concept Drift and Statistical Residual Monitoring (report §5.8).

Implements the Page-Hinkley test and rolling window error monitors to detect when
external environmental shifts (e.g. seasonal monsoons, ocean swell, pilot shortages)
cause model predictions to systematically drift away from actual vessel dynamics.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class DriftSignal:
    drift_detected: bool
    drift_type: str  # NONE | MEAN_SHIFT | VARIANCE_SPIKE | BIAS_DRIFT
    statistic: float
    threshold: float
    sample_size: int
    recommendation: str


class ConceptDriftDetector:
    """Detects concept drift in streaming ETA prediction errors using Page-Hinkley test."""

    def __init__(
        self,
        threshold: float = 40.0,
        delta: float = 5.0,
        min_samples: int = 10,
        reference_mean: float = 0.0,
    ):
        """Args:

        threshold: Cumulative deviation required to trigger drift alarm.
        delta: Permissible tolerance parameter for acceptable error fluctuation.
        min_samples: Minimum observations required before evaluating drift.
        reference_mean: Expected unbiased residual mean (defaults to 0.0).
        """
        self.threshold = threshold
        self.delta = delta
        self.min_samples = min_samples
        self.reference_mean = reference_mean

    def check_residuals(self, errors_minutes: List[float]) -> DriftSignal:
        """Run Page-Hinkley change detection on signed prediction errors."""
        n = len(errors_minutes)
        if n < self.min_samples:
            return DriftSignal(
                drift_detected=False,
                drift_type="NONE",
                statistic=0.0,
                threshold=self.threshold,
                sample_size=n,
                recommendation=f"Collecting initial sample baseline ({n}/{self.min_samples}).",
            )

        mean_err = sum(errors_minutes) / n

        # Page-Hinkley cumulative sum against expected nominal reference (0.0)
        cumulative_sum = 0.0
        min_cumulative_sum = 0.0
        ph_stat = 0.0

        for e in errors_minutes:
            cumulative_sum += e - self.reference_mean - self.delta
            if cumulative_sum < min_cumulative_sum:
                min_cumulative_sum = cumulative_sum
            current_diff = cumulative_sum - min_cumulative_sum
            if current_diff > ph_stat:
                ph_stat = current_diff

        drift_flag = ph_stat >= self.threshold

        if drift_flag:
            direction = "late (vessels arriving later than predicted)" if mean_err > 0 else "early"
            rec = (
                f"Statistical drift detected (PH statistic {ph_stat:.1f} >= {self.threshold:.1f}). "
                f"Systematic bias: arrivals are averaging {abs(mean_err):.1f} min {direction}. "
                f"Triggering automated HistGradientBoosting model retraining."
            )
            dtype = "MEAN_SHIFT"
        else:
            rec = (
                f"Process stable: Page-Hinkley stat {ph_stat:.1f} within tolerance "
                f"(threshold {self.threshold:.1f})."
            )
            dtype = "NONE"

        return DriftSignal(
            drift_detected=drift_flag,
            drift_type=dtype,
            statistic=round(ph_stat, 2),
            threshold=self.threshold,
            sample_size=n,
            recommendation=rec,
        )
