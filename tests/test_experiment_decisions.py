"""Conditional impact arithmetic is not a performance predictor or acceptance gate."""

import math

import pytest

from inferrsi.harness.experiment_decisions import forecast


def estimate(fraction, speedup, overhead=(0, 0)):
    return {"kind": "conditional_serial_latency", "fraction": list(fraction),
            "local_speedup": list(speedup), "overhead_fraction": list(overhead),
            "assumptions": "Synthetic serial exposed-time example, no overlap",
            "input_evidence": "Synthetic arithmetic fixture, not hardware measurements"}


def test_local_speedup_does_not_rank_whole_task_impact():
    tiny = forecast(estimate((.05, .05), (10, 10)))
    large = forecast(estimate((.4, .4), (1.5, 1.5)))
    assert tiny["speedup_range"] == pytest.approx([1 / .955] * 2)
    assert large["speedup_range"] == pytest.approx([1 / (.6 + .4 / 1.5)] * 2)
    assert tiny["speedup_range"][1] < large["speedup_range"][0]
    assert forecast(estimate((.05, .05), (10, 10), (.1, .1)))["speedup_range"][0] < 1


def test_range_handles_local_slowdown_and_added_overhead():
    result = forecast(estimate((.2, .6), (.5, 2), (0, .1)))
    assert result["speedup_range"] == pytest.approx([1 / 1.7, 1 / .7])
    assert forecast({"kind": "unknown", "reason": "No exposed-time breakdown",
                     "next_check": "Targeted trace"})["speedup_range"] is None


@pytest.mark.parametrize("field,value", [
    ("fraction", [-.1, .5]), ("fraction", [0, 1.1]), ("fraction", [True, 1]),
    ("local_speedup", [0, 2]), ("local_speedup", [2, 1]),
    ("overhead_fraction", [-1, 0]), ("fraction", [math.nan, 1]),
    ("local_speedup", [1, math.inf]),
])
def test_invalid_ranges_do_not_produce_a_rank(field, value):
    impact = estimate((.2, .6), (1, 2))
    impact[field] = value
    with pytest.raises(ValueError):
        forecast(impact)


def test_concurrency_and_missing_evidence_are_not_serial_latency_estimates():
    impact = estimate((.2, .6), (1, 2))
    impact["kind"] = "throughput_at_slo"
    with pytest.raises(ValueError):
        forecast(impact)
    impact = estimate((.2, .6), (1, 2))
    impact["input_evidence"] = ""
    with pytest.raises(ValueError):
        forecast(impact)
