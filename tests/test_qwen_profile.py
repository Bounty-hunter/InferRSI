"""Trace diagnostics do not invent device activity or additive whole-task timing."""

import importlib.util
from pathlib import Path

import pytest

PATH = (Path(__file__).parents[1] / "src/inferrsi/benchmark/tasks/qwen21-denoise-npu"
        / "profile_workload.py")
SPEC = importlib.util.spec_from_file_location("qwen_profile", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_cpu_only_trace_is_not_complete_npu_profile():
    events = [{"ph": "X", "cat": "cpu_op", "name": "aten::linear", "dur": 2000},
              {"ph": "X", "cat": "cpu_op", "name": "aten::mm", "dur": 1000},
              {"ph": "M", "name": "process_name", "args": {"name": "Ascend Hardware"}}]
    summary = MODULE.trace_summary(events)
    assert MODULE.observed_activities(summary) == {"cpu": True, "npu": False}
    assert summary[0]["summed_event_ms_not_wall_time"] == pytest.approx(3)
    events.append({"ph": "X", "cat": "kernel", "name": "MatMul", "dur": 500})
    summary = MODULE.trace_summary(events)
    assert MODULE.observed_activities(summary) == {"cpu": True, "npu": True}
    assert len(summary) == 2  # Device and nested host durations stay in separate categories.
