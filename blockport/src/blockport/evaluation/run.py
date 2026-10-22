"""CLI runner for the Comprehensive Evaluation Harness (report §3, §8).

    python -m blockport.evaluation.run
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .harness import EvaluationHarness


def main() -> None:
    parser = argparse.ArgumentParser(description="BlockPort AI System Benchmark Evaluation")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    parser.add_argument("--out", type=str, default=None, help="Save markdown report to file")
    args = parser.parse_args()

    harness = EvaluationHarness()
    scorecard = harness.run_full_evaluation()

    if args.json:
        print(json.dumps(scorecard.to_dict(), indent=2))
    else:
        print("\n" + scorecard.to_markdown() + "\n")

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(scorecard.to_markdown())
        print(f"Benchmark scorecard saved to: {out_path.resolve()}")


if __name__ == "__main__":
    main()
