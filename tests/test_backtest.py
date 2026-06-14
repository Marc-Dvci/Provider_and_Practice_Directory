from __future__ import annotations

from directory_pipeline.backtest import run_backtest, run_scale_backtest


def test_backtest_metrics_on_sample():
    report = run_backtest()
    assert report.records == 6
    assert report.true_changes == 9
    # The shipped stand-in is small and clean -> perfect scores; the value is the
    # method (real national backtests show the realistic numbers).
    assert report.recall == 1.0
    assert report.detection_precision == 1.0
    assert report.auto_update_precision == 1.0
    assert report.routing_accuracy == 1.0
    assert 0.0 <= report.brier <= 0.1
    assert report.render()  # renders without error


def test_scale_backtest_is_realistic_and_deterministic():
    # A larger synthetic world (seeded -> deterministic) exercises the full pipeline
    # and yields realistic, non-perfect accuracy with a meaningful calibration curve.
    report = run_scale_backtest(600, seed=0)
    assert report.records == 600
    assert report.detected_changes >= 30  # enough for a real calibration curve
    assert 0.90 <= report.recall <= 1.0
    assert 0.90 <= report.auto_update_precision < 1.0  # noise -> some wrong auto-updates
    assert report.routing_accuracy >= 0.95
    assert report.brier < 0.15
    # Same seed -> identical headline numbers.
    again = run_scale_backtest(600, seed=0)
    assert again.auto_update_precision == report.auto_update_precision
