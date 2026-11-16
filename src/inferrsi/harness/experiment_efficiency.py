"""Concise search feedback. No prediction, ranking or acceptance authority."""

import json


def guidance():
    return [
        "Optimize best valid whole-task performance within the total budget. Read search_context "
        "and the current code before choosing the next action. A normal round needs only its "
        "hypothesis; numerical forecasts and a separate propose call are optional.",
        "Use applicable runtime evidence to identify exposed work, launch gaps and overlap. "
        "If evidence is missing or stale, collect targeted profiling when it can change the "
        "choice. Whole-task timing alone does not identify a bottleneck. "
        "Do not profile every round.",
        "Keep a few distinct directions when useful, including ideas formed before retrieval. "
        "Compare mechanism, applicability, potential whole-task impact, implementation cost and "
        "risk. Retrieval rank and guessed speedup are not priorities. Unknown impact may still "
        "justify exploration; prerequisite changes need not improve performance alone.",
        "Reuse retained knowledge and diagnostics when their code/workload assumptions still hold. "
        "Query only a concrete missing fact; do not reread a large corpus each round. A failed "
        "or no-gain idea needs changed evidence or a specific repair before repeating it.",
        "If an inexpensive check could change the next action, use diagnose with a question, "
        "different if-supported/if-rejected actions, and a bounded command. Otherwise implement "
        "directly. Diagnostics are advisory, consume time and tokens, and never promote code. "
        "Reduced shapes or isolated kernels do not prove whole-task performance.",
        "After each round inspect the measured result and why it failed or was not retained. "
        "Restore the best code before an unrelated change; keep exploration bounded and reserve "
        "time for final. Follow round_mode: up_to allows an explained early stop; exact does not. "
        "Do not stop merely because one candidate passed. Report missing usage as unknown.",
    ]


def brief(record):
    assessment = record["assessment"]
    return {
        "path": record["path"] + "/observation.json",
        "candidate_sha256": record["candidate_sha256"],
        "hypothesis": record["hypothesis"],
        "assessment": {key: assessment.get(key) for key in (
            "status", "verdict", "score", "eligible", "reason", "quality_passed")},
        "best_after": record.get("best_after"),
        "elapsed_seconds": record.get("elapsed_seconds"),
        "decision_feedback": record.get("decision_feedback"),
    }


def context(root, plan, state):
    """Project retained facts, without claiming that stale evidence applies now."""
    rounds = state["rounds"]
    diagnostics = state.get("diagnostics", [])
    profiles = {}
    for reference in state.get("decisions", []):
        receipt = json.loads((root / reference["path"]).read_text(encoding="utf-8"))
        if profile := receipt.get("profile_artifact"):
            profiles[profile["sha256"]] = {
                **profile, "relation": "current" if profile["source_sha256"] == (
                    state["best"]["sha256"]) else "historical_recheck_applicability"}
    elapsed = [r.get("elapsed_seconds") for r in [*rounds, *diagnostics]]
    return {
        "objective": plan["selection"],
        "recent_attempts": [brief(r) for r in rounds[-8:]],
        "omitted_attempts": max(0, len(rounds) - 8),
        "knowledge": list(state["contexts"][-5:]),
        "omitted_contexts": max(0, len(state["contexts"]) - 5),
        "profiles": list(profiles.values())[-3:],
        "diagnostics": [{key: r.get(key) for key in (
            "path", "question", "if_supported", "if_rejected", "basis_sha256",
            "status", "elapsed_seconds")} for r in diagnostics[-5:]],
        "observed_execution_seconds": sum(v for v in elapsed if v is not None),
        "missing_execution_durations": sum(v is None for v in elapsed),
        "cost_scope": "Measured command wall time includes allocator waits; excludes Agent "
                      "reasoning/retrieval. Use session wall time and native usage for total cost.",
        "evidence_rule": "Scores use the frozen baseline, not a matched comparison against "
                         "the current best. Diagnostic success is not task acceptance.",
    }
