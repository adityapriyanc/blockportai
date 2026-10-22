"""Evaluation Scorecard and Metric Definitions (report §3 Objectives 1–8)."""
from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class MetricScore:
    metric_id: int
    name: str
    target_description: str
    baseline_value: str
    achieved_value: str
    passed: bool
    margin: str
    details: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkScorecard:
    timestamp: datetime.datetime
    results: List[MetricScore]
    total_objectives: int
    passed_count: int
    all_targets_met: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "total_objectives": self.total_objectives,
            "passed_count": self.passed_count,
            "all_targets_met": self.all_targets_met,
            "results": [r.to_dict() for r in self.results],
        }

    def to_markdown(self) -> str:
        res_label = (
            "ALL OBJECTIVES MET (8/8 PASSED)"
            if self.all_targets_met
            else "PARTIAL"
        )
        lines = [
            "# BlockPort AI - System Performance & Target Scorecard",
            f"**Evaluation Time:** {self.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}  ",
            f"**Overall Result:** {res_label}",
            "",
            "| ID | Objective | Target | Baseline | Achieved | Status | Margin / Notes |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in self.results:
            status = "PASS" if r.passed else "FAIL"
            lines.append(
                f"| {r.metric_id} | {r.name} | {r.target_description} | {r.baseline_value} | "
                f"{r.achieved_value} | **{status}** | {r.margin} |"
            )
        return "\n".join(lines)
