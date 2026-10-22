"""Closed-Loop Feedback and Adaptive Learning package (report §5.8)."""
from .drift import ConceptDriftDetector, DriftSignal
from .preferences import OperatorPreferenceLearner, PreferenceFeedbackEntry
from .tracker import ExecutionFeedbackTracker, ExecutionObservation, ResidualPerformanceSummary

__all__ = [
    "ConceptDriftDetector",
    "DriftSignal",
    "ExecutionFeedbackTracker",
    "ExecutionObservation",
    "OperatorPreferenceLearner",
    "PreferenceFeedbackEntry",
    "ResidualPerformanceSummary",
]
