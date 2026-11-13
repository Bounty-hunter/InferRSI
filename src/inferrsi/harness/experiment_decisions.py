"""Validate caller-supplied experiment choices; forecasts never establish acceptance."""

import hashlib
import itertools
import json
import math
from pathlib import Path

from ..infra.artifacts import sha256


def guidance():
    """Short operational bridge to the existing search-policy and ceiling methods."""
    return [
        "Start from the current code, fixed objective, latest observation and remaining budget. "
        "Read an actual runtime profile of this workload before choosing the first experiment. "
        "If none exists, collect one using the task's diagnostic entry or the project's profiler; "
        "source inspection and whole-task timings are not a profile. Retain the raw evidence.",
        "Keep a small shortlist of distinct mechanisms, including independently formed ideas. "
        "Use the profile to explain affected work, call counts, host/device gaps and overlap. "
        "Separate measured observations from assumptions about an unwritten implementation.",
        "Compare whole-task impact, evidence, implementation/verification cost and risk. "
        "Give an agent_estimate range for new/current objective with observations, assumptions "
        "and derivation, or use conditional_serial_latency when its serial assumptions hold. "
        "An unmeasured local speedup may be an explicit hypothesis; it is not by itself a reason "
        "to use unknown. Do not sum overlapping kernel times as an end-to-end time fraction.",
        "Choose one experiment yourself; neither retrieval rank nor the largest guessed number "
        "determines the choice. Use unknown only when no defensible range can be given, explaining "
        "the missing evidence in impact.reason and the next discriminating check in "
        "impact.next_check. A demo is optional: probe if its result could change the choice "
        "and its total cost is worthwhile; otherwise directly implement and evaluate.",
        "Select action=implement before editing; explain the tradeoff and preserve viable "
        "alternatives. Allow bounded exploration rather than only predictable small changes.",
        "After evaluation read decision_feedback and revise the next choice. Reuse a profile only "
        "with an explicit applicability explanation; refresh when bottlenecks may have shifted. "
        "Do not require profiling or retrieval every round. Count analysis, "
        "retrieval, probes, failures and validation in the budget; forecasts never pass gates.",
    ]


def template(basis_sha256):
    """Expose the minimal contract to installed CLI callers without repository docs."""
    return {"schema_version": 1, "based_on_sha256": basis_sha256,
            "profile": {"path": "<profile summary JSON, relative to campaign directory>",
                        "applicability": "<profiled source/workload and relevance now>"},
            "alternatives": [{"id": "<alternative-id>", "change": "<proposed change>",
                "mechanism": "<why it affects the current workload>",
                "evidence": ["<source or measurement reference>"],
                "cost": "<editing and verification cost or unknown>",
                "risk": "<correctness and performance uncertainty>",
                "impact": {"kind": "agent_estimate", "objective_ratio_range": [None, None],
                           "observations": "<measured profile facts and source references>",
                           "assumptions": "<hypothesized local gain, overhead and uncertainty>",
                           "derivation": "<derive new/current objective range>"}}],
            "selected": "<alternative-id>", "action": "implement",
            "rationale": "<tradeoff, latest feedback and cheapest check that changes the choice>"}


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Decision requires nonempty {field}")
    return value


def retain_profile(root, payload, state):
    """Retain a supplied diagnostic summary; integrity is not scientific validation."""
    profile = payload.get("profile")
    if profile is None:
        return None  # Older recorded decisions remain readable and supported.
    if not isinstance(profile, dict):
        raise ValueError("Profile must be an object")
    path = Path(_text(profile.get("path"), "profile path"))
    if not path.is_absolute():
        path = root / path
    applicability = _text(profile.get("applicability"), "profile applicability")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 262144:
        raise ValueError("Profile summary must be a regular JSON file within 256 KiB")
    raw = path.read_bytes()
    report = json.loads(raw)
    if (not isinstance(report, dict) or report.get("kind") != "runtime_profile"
            or report.get("status") != "completed"):
        raise ValueError("A completed runtime profile summary is required")
    _text(report.get("profiler"), "profiler name")
    known = {state["best"]["sha256"]}
    known.update(item["candidate_sha256"] for item in state["rounds"])
    # A baseline profile remains usable after promotion, with explicit applicability.
    known.add(json.loads((root / "plan.json").read_text(encoding="utf-8"))["baseline_sha256"])
    identity = report.get("source_sha256")
    if identity not in known:
        raise ValueError("Profile source is not a retained campaign implementation")
    fingerprint = hashlib.sha256(raw).hexdigest()
    target = root / "decision-evidence" / ("profile-" + fingerprint + ".json")
    target.parent.mkdir(exist_ok=True)
    if target.exists():
        if sha256(target) != fingerprint:
            raise ValueError("Retained profile summary changed")
    else:
        target.write_bytes(raw)
    return {"path": target.relative_to(root).as_posix(), "sha256": fingerprint,
            "source_sha256": identity, "applicability": applicability,
            "relation": "current" if identity == state["best"]["sha256"] else "historical",
            "evidence_status": "retained_caller_diagnostic_not_independently_verified"}


def _range(value, field, *, positive=False, maximum=None):
    if (not isinstance(value, list) or len(value) != 2
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in value)
            or value[0] > value[1] or value[0] < 0
            or (positive and value[0] == 0)
            or (maximum is not None and value[1] > maximum)):
        raise ValueError(f"Invalid conditional range: {field}")
    return value


def forecast(impact):
    if not isinstance(impact, dict):
        raise ValueError("Impact must be an object")
    if impact.get("kind") == "unknown":
        _text(impact.get("reason"), "impact.reason for unknown impact")
        _text(impact.get("next_check"), "impact.next_check (next discriminating check)")
        return {"kind": "unknown", "speedup_range": None}
    if impact.get("kind") == "agent_estimate":
        bounds = _range(impact.get("objective_ratio_range"), "objective_ratio_range", positive=True)
        for field in ("observations", "assumptions", "derivation"):
            _text(impact.get(field), field)
        return {"kind": "agent_estimate", "objective_ratio_range": bounds,
                "ratio_definition": "new_candidate_objective / current_incumbent_objective",
                "evidence_status": "agent_hypothesis_not_measured_or_calibrated",
                "speedup_range": None}
    if impact.get("kind") != "conditional_serial_latency":
        raise ValueError("Use agent_estimate, unknown or conditional_serial_latency impact")
    _text(impact.get("assumptions"), "serial/exposed-time assumptions")
    _text(impact.get("input_evidence"), "conditional input evidence")
    fraction = _range(impact.get("fraction"), "fraction", maximum=1)
    local = _range(impact.get("local_speedup"), "local_speedup", positive=True)
    overhead = _range(impact.get("overhead_fraction"), "overhead_fraction")
    values = []
    for share, acceleration, added in itertools.product(fraction, local, overhead):
        remaining = (1 - share) + share / acceleration + added
        if not math.isfinite(remaining) or remaining <= 0:
            raise ValueError("Conditional arithmetic must remain finite and positive")
        value = 1 / remaining
        if not math.isfinite(value):
            raise ValueError("Conditional speedup must be finite")
        values.append(value)
    return {"kind": "conditional_serial_latency", "speedup_range": [min(values), max(values)],
            "evidence_status": "caller_supplied_assumptions_not_verified_measurements"}


def assess(payload, *, basis_sha256):
    if (not isinstance(payload, dict) or type(payload.get("schema_version")) is not int
            or payload["schema_version"] != 1):
        raise ValueError("Decision schema_version must be 1")
    if payload.get("based_on_sha256") != basis_sha256:
        raise ValueError("Decision must reference the current selected candidate")
    alternatives = payload.get("alternatives")
    if not isinstance(alternatives, list) or not 1 <= len(alternatives) <= 8:
        raise ValueError("Provide one to eight bounded alternatives")
    predictions = {}
    for alternative in alternatives:
        if not isinstance(alternative, dict):
            raise ValueError("Each alternative must be an object")
        identity = _text(alternative.get("id"), "alternative id")
        if identity in predictions:
            raise ValueError("Alternative ids must be unique")
        for field in ("change", "mechanism", "cost", "risk"):
            _text(alternative.get(field), field)
        evidence = alternative.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("Each alternative must state its evidence")
        for item in evidence:
            _text(item, "evidence reference or observation")
        predictions[identity] = forecast(alternative.get("impact"))
    selected = _text(payload.get("selected"), "selected alternative")
    if selected not in predictions:
        raise ValueError("Selected alternative must appear in the shortlist")
    _text(payload.get("rationale"), "selection rationale")
    action = payload.get("action", "implement")
    if action not in ("implement", "probe"):
        raise ValueError("Decision action must be implement or probe")
    return {"selected": selected, "action": action, "forecasts": predictions,
            "effect": "experiment_choice_only_not_quality_or_performance_acceptance"}


def feedback(receipt, record, selection):
    """Connect the forecast to actual assessment without inventing comparable timing."""
    choice = receipt["assessment"]
    assessment = record["assessment"]
    return {
        "selected": choice["selected"], "basis": receipt["basis"],
        "forecast": choice["forecasts"][choice["selected"]],
        "observed": {"candidate_sha256": record["candidate_sha256"],
                     "metric": selection["metric"], "direction": selection["direction"],
                     **{key: assessment.get(key) for key in (
                         "status", "verdict", "score", "eligible", "reason")},
                     "retained_as_best": (
                         record["candidate_sha256"] == record["best_after"]["sha256"]
                         and record["candidate_sha256"] != receipt["basis"]["sha256"])},
        "calibration": {"status": "not_established", "speedup_vs_decision_basis": None,
                        "reason": "The protocol measures against its frozen baseline. "
                        "The forecast concerns the decision basis; historical scores alone "
                        "do not establish a matched comparison or prediction error."},
        "next_step": "Use the assessment and any new evidence to revise the shortlist, "
                     "cost and assumptions. Keep failed and no-gain choices visible.",
    }
