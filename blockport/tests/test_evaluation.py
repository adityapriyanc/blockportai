"""Tests for the Comprehensive Evaluation Harness (report §3, §8)."""
from blockport.evaluation.harness import EvaluationHarness


def test_full_evaluation_harness_passes_all_8_targets():
    harness = EvaluationHarness()
    scorecard = harness.run_full_evaluation()

    assert scorecard.total_objectives == 8
    assert scorecard.passed_count == 8
    assert scorecard.all_targets_met is True

    # Check individual targets
    for res in scorecard.results:
        assert res.passed is True
        assert len(res.margin) > 0

    md = scorecard.to_markdown()
    assert "ALL OBJECTIVES MET (8/8 PASSED)" in md
    assert "| 1 |" in md
    assert "| 8 |" in md
