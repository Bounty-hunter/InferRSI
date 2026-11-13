# SPDX-License-Identifier: Apache-2.0
"""Profile the supplied denoiser; diagnostics never qualify a candidate or score."""

import argparse
import collections
import hashlib
import importlib.util
import json
import os
import statistics
import time
from pathlib import Path


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def trace_summary(events):
    """Keep categories separate: inclusive CPU durations cannot be added to kernels."""
    groups = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0.0]))
    for event in events:
        if event.get("ph") != "X" or not isinstance(event.get("dur"), (int, float)):
            continue
        duration = event["dur"]
        if duration <= 0:
            continue
        category = str(event.get("cat", "uncategorized"))
        row = groups[category][str(event.get("name", "unnamed"))]
        row[0] += 1
        row[1] += duration
    return [{"category": category, "event_count": sum(r[0] for r in rows.values()),
             "summed_event_ms_not_wall_time": sum(r[1] for r in rows.values()) / 1000,
             "top_events": [{"name": name, "calls": count, "inclusive_ms": duration / 1000}
                            for name, (count, duration) in sorted(
                                rows.items(), key=lambda item: item[1][1], reverse=True)[:20]]}
            for category, rows in sorted(groups.items())]


def observed_activities(categories):
    observed = {c["category"].lower() for c in categories}
    return {"cpu": "cpu_op" in observed, "npu": "kernel" in observed}


def run(args):
    # Import only inside the caller's allocated NPU execution.
    visible = os.environ.get("ASCEND_RT_VISIBLE_DEVICES", "").split(",")
    if len(visible) != 1 or not visible[0].strip().isdigit():
        raise ValueError("Run inside one caller-owned NPU allocation, e.g. npu run --gpus 1")
    import torch
    import torch_npu

    torch.npu.set_device(0)
    torch.npu.matmul.allow_hf32 = False
    torch.set_num_threads(8)
    root = Path(__file__).resolve().parent
    task = json.loads((root / "task.json").read_text(encoding="utf-8"))
    workload = load(root / "workload.py", "profile_workload_inputs")
    source = args.candidate.read_bytes()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    snapshot = args.output_dir / "candidate.py"
    snapshot.write_bytes(source)
    compute = load(snapshot, "profile_candidate").compute
    selected = [(index, case) for index, case in enumerate(task["cases"])
                if case["id"] in args.case] if args.case else [
                    (index, case) for index, case in enumerate(task["cases"]) if case["measured"]]
    if not selected or (args.case and set(args.case) != {c["id"] for _, c in selected}):
        raise ValueError("Select existing task case IDs")
    report = {"schema_version": 1, "kind": "runtime_profile", "status": "running",
              "profiler": "torch_npu.profiler CPU+NPU",
              "source_sha256": hashlib.sha256(source).hexdigest(),
              "task_sha256": hashlib.sha256((root / "task.json").read_bytes()).hexdigest(),
              "runtime": {"torch": torch.__version__, "torch_npu": torch_npu.__version__,
                          "device": torch.npu.get_device_name(0), "dtype": "bfloat16"},
              "cases": [], "limitations": [
                  "Diagnostic only: no correctness verdict or optimization score.",
                  "Profiled durations include instrumentation; unprofiled samples are separate.",
                  "Inclusive/nested CPU events and overlapping device events are not additive.",
                  "Kernel time share is not exposed whole-request time share.",
                  "Map events to source and state overlap/overhead assumptions before estimating.",
                  "A subset of cases cannot establish the full task's aggregate benefit."]}
    started = time.monotonic()
    try:
        with torch.inference_mode():
            for index, case in selected:
                config = {**task["defaults"], **case}
                params = workload.parameters(config, 1701 + index, "npu:0", torch.bfloat16)
                samples = []
                for request in range(args.warmups + args.samples):
                    inputs = workload.inputs(config, 9001 + index * 1000 + request,
                                             "npu:0", torch.bfloat16)
                    torch.npu.synchronize()
                    tick = time.perf_counter()
                    compute(*inputs, params, config=config)
                    torch.npu.synchronize()
                    if request >= args.warmups:
                        samples.append((time.perf_counter() - tick) * 1000)
                inputs = workload.inputs(config, 9001 + index * 1000 + args.warmups + args.samples,
                                         "npu:0", torch.bfloat16)
                torch.npu.synchronize()
                with torch_npu.profiler.profile(
                    activities=[torch_npu.profiler.ProfilerActivity.CPU,
                                torch_npu.profiler.ProfilerActivity.NPU],
                    record_shapes=True, with_stack=False,
                ) as profiler:
                    with torch.profiler.record_function("denoise_request"):
                        compute(*inputs, params, config=config)
                        torch.npu.synchronize()
                trace = args.output_dir / (case["id"] + "-trace.json")
                profiler.export_chrome_trace(str(trace))
                data = json.loads(trace.read_text(encoding="utf-8"))
                events = data if isinstance(data, list) else data["traceEvents"]
                categories = trace_summary(events)
                coverage = observed_activities(categories)
                report["cases"].append({"id": case["id"], "config": config,
                    "unprofiled_request_samples_ms": samples,
                    "unprofiled_request_median_ms": statistics.median(samples),
                    "trace": trace.name,
                    "trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
                    "observed_activities": coverage, "categories": categories})
                if not all(coverage.values()):
                    raise ValueError("Incomplete CPU/NPU coverage; inspect retained raw trace")
        if args.candidate.read_bytes() != source or snapshot.read_bytes() != source:
            raise ValueError("Profiled source changed during collection")
        report["status"] = "completed"
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        (args.output_dir / "profile.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "summary": str(args.output_dir / "profile.json"),
                      "cases": [c["id"] for c in report["cases"]]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case", action="append")
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--samples", type=int, default=3)
    args = parser.parse_args()
    if args.warmups < 1 or args.samples < 1:
        parser.error("Use positive warmups and samples")
    run(args)


if __name__ == "__main__":
    main()
