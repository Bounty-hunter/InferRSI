# Recorded experiment decisions

This opt-in Harness path retains why an Agent chose the next experiment, including
expected impact and uncertainty. It works for ordinary `campaign` requests and
packaged `benchmarks session` tasks, with knowledge enabled or disabled. It does
not rank alternatives automatically, certify Agent predictions, or
change correctness, promotion or final-evaluation rules.

The recorded guidance now starts from an actual runtime profile, then asks the
Agent to estimate and select. Use an existing applicable profile or collect one
with the task/project's tools. Whole-task timers and source inspection are not
profiling. Refresh when the bottleneck may have changed, not mechanically each
round. The Agent may hypothesize an unwritten implementation's local speedup;
unmeasured assumptions must be labeled, but do not alone force `unknown`.
No microbenchmark or automated prediction service is required.

`agent_estimate` impact contains a positive ordered `objective_ratio_range`
(`new candidate objective / current incumbent objective`), and nonempty
`observations`, `assumptions` and `derivation` strings. For latency minimization,
a ratio below one is better; for throughput or speedup maximization, above one
is better. The returned `decision_objective` gives the metric and direction.
Explain how observed hotspots, call counts and overlap support the estimate,
and how speculative local gains and added overhead produce the aggregate range.
These are Agent hypotheses, not measurements or calibrated confidence intervals.
Do not use raw kernel duration shares as exposed request-time fractions.

Attach `profile: {"path": "<summary.json>", "applicability": "<why relevant now>"}`
to a proposal. Relative paths resolve against the campaign. A supplied summary
must be JSON with `kind: runtime_profile`, `status: completed`, `profiler`, and
`source_sha256` matching a retained campaign implementation (for a project, its
declared candidate-tree identity). Harness retains and hashes the summary,
checks it on subsequent operations, and labels older-source evidence historical.
This establishes provenance and integrity, not the correctness of the diagnostic
or its interpretation. Keep raw traces with the campaign's diagnostic artifacts.
Old proposals without `profile` remain valid for compatibility; the Agent-facing
workflow requests profiling, rather than claiming Python can prove it happened.

The Qwen task supplies `profile_workload.py`, whose command and limitations are
in its TASK.md. It profiles the supplied implementation on the task's measured
shapes and returns CPU/NPU trace summaries and separate unprofiled request times.
Task-specific profiling stays in the task, outside common Harness code.

Choose `--decision-policy recorded` when starting a new campaign with the usual
task, budget and evaluation arguments. The default `agent` policy preserves the
existing workflow. Policy choice is frozen with the plan. A recorded campaign
returns `submit_experiment_decision_before_editing` before each round.
Its `decision_template` includes the current source identity and required JSON
fields, so an installed CLI caller does not need a repository docs checkout.
The start response also delivers a short `decision_guidance` procedure. This
bridges the existing search-policy and ceiling-analysis methods into the actual
loop: compare distinct mechanisms, evidence, whole-task impact, cost and risk;
resolve a decision-changing uncertainty cheaply; then use measured feedback to
revise the next choice. Retrieval and full profiling are not mandatory per round.

Before editing the next candidate, inspect current code and evidence, optionally
consult knowledge, then submit a small shortlist and your choice:

```bash
inferrsi campaign propose --session <campaign-directory> --input <decision.json>
# Packaged tasks expose the identical operation:
inferrsi benchmarks session propose --session <campaign-directory> --input <decision.json>
```

The JSON contract is:

```json
{
  "schema_version": 1,
  "based_on_sha256": "<best.sha256 returned by status>",
  "profile": {
    "path": "diagnostics/profile-01/profile.json",
    "applicability": "<profiled source, workload coverage and applicability to current code>"
  },
  "alternatives": [
    {
      "id": "reuse",
      "change": "Reuse an invariant intermediate inside each request",
      "mechanism": "Remove repeated work without retaining state across requests",
      "evidence": ["<source location or measurement reference>", "<knowledge reference if used>"],
      "cost": "<editing, diagnostic and verification work in stated units or a qualitative range>",
      "risk": "<correctness, lifetime, precision and performance uncertainties>",
      "impact": {
        "kind": "agent_estimate",
        "objective_ratio_range": [null, null],
        "observations": "<measured profile facts>",
        "assumptions": "<hypothesized local gain and additional costs>",
        "derivation": "<how these imply a new/current aggregate objective range>"
      }
    }
  ],
  "selected": "reuse",
  "action": "implement",
  "rationale": "<why this experiment is preferable now; retain other viable directions>"
}
```

Replace both null placeholders with your estimated numerical bounds. Use one to
eight alternatives and keep the input within 64 KiB. Evidence strings
are caller assertions; this command does not fetch them or certify their truth.
An unknown impact is valid and has no numerical forecast. Do not invent numbers
to satisfy the workflow. A small full-task contrast can be cheaper than profiling;
choose diagnostic work only when it resolves a concrete uncertainty.

Use `action: "probe"` when a diagnostic is the best next action. The CLI returns
`run_selected_probe_then_revise_decision` and refuses a candidate round until a
replacement implementation decision is submitted. Run the probe through the
existing execution/resource workflow, retain its result, then `propose` again
with the new evidence. The earlier decision remains as `supersedes`; proposals
do not consume optimization rounds, but their work still consumes time and
tokens. Omitting `action` means `implement` for compatibility.

When a serial exposed-latency decomposition is justified, `impact` may instead
use `kind: "conditional_serial_latency"` with:

- `fraction`: `[lower, upper]` fraction of the current implementation's total
  exposed latency attributable to the affected work, within zero and one.
- `local_speedup`: positive `[lower, upper]` acceleration of that work. Values
  below one allow a potential local regression.
- `overhead_fraction`: nonnegative `[lower, upper]` additional exposed latency,
  normalized to the same current implementation.
- `assumptions` and `input_evidence`: nonempty explanations of the decomposition,
  overlap exclusions, workload match and provenance of the numerical ranges.

Harness evaluates the corners of `1 / ((1-f) + f/s + h)` and returns a
conditional range explicitly labeled as unverified caller assumptions. This is
an arithmetic envelope, not a calibrated confidence interval, achievable bound
or measurement. It does not sum overlapping kernels or model throughput/SLOs.
Use unknown when these assumptions do not hold. See the existing
[headroom skill](../src/inferrsi/data/skill_library/methods/performance-ceiling-analysis/SKILL.md)
for selecting evidence. The search-policy skill remains the method owner; this
optional control path does not create a second knowledge library.

The operation creates a hashed `decisions/decision-<id>.json`, binds it to the
current incumbent identity and next round number, and records a pending reference
in `state.json`. A replacement proposal preserves and supersedes the earlier
receipt. It does not consume an optimization round or launch a process.

`round` rejects a missing receipt under the recorded policy, rejects stale or
modified receipts, then binds the receipt to the submitted candidate and consumes
it when the attempt settles. A failed experiment still retains the decision and
failure. Pending-attempt recovery uses the same receipt. Summaries expose the
references alongside the measured curve; input forecasts never supply a score.
`final` independently retests the controller-selected implementation as before.

Each settled choice produces `decision_feedback`, returned with the next status
and retained in the observation and summary curve. It links the chosen forecast
to the actual assessment and whether the candidate was retained. Failed and
no-gain choices stay visible. A forecast against the current incumbent must not
be compared blindly to a score measured against the original baseline: historical
score ratios are not matched experiments. The generic feedback leaves numerical
calibration unestablished; use additional matched evidence for a prediction-error
claim. Feedback never changes the evaluator or candidate promotion rules.

## Before and after

| Stage | Default `agent` policy | Opt-in `recorded` policy |
| --- | --- | --- |
| Start | Freeze task, quality/performance protocol and budget | Same, plus freeze policy and return choice guidance/template |
| Next experiment | Agent edits and supplies a hypothesis | Agent compares alternatives, impact/evidence/cost/risk and submits `propose` before editing |
| Uncertainty | Agent decides whether to investigate | Explicit `probe` can pause implementation until a revised choice; no forced profiling |
| Round | Retain and evaluate submitted candidate | Also reject missing, stale or altered decisions and bind the choice to the attempt |
| Feedback | Assessment and incumbent | Same, plus chosen forecast, measured outcome and comparison limitations |
| Final | Independently retest the selected code | Unchanged; predictions cannot qualify a candidate |

Both ordinary user tasks and packaged tasks call the shared controller. The
current lifecycle is a legacy mixed implementation; this change adds no new core
component or cross-module import. Follow the accepted K/H/B contracts when that
lifecycle is migrated; do not treat this file location as the target boundary.

## Method sources and efficacy checks

- [Ansor](https://www.usenix.org/conference/osdi20/presentation/zheng) allocates
  tuning effort by potential whole-model improvement. Its structured schedule
  cost model is not a predictor for arbitrary repository edits.
- [AutoKernel](https://arxiv.org/html/2603.21331v1) illustrates hotspot what-if
  analysis. Assumed local speedup remains an assumption, not a calibrated forecast.
- [Cost-aware Bayesian optimization](https://papers.nips.cc/paper_files/paper/2012/hash/05311655a15b75fab86956663e1819cd-Abstract.html)
  motivates considering improvement and evaluation cost together. This feature
  does not implement Bayesian optimization or invent success probabilities.

Freeze the comparison before search. Hold model, task, corpus, retrieval method,
quality gates and budgets constant, and compare fresh Agent trajectories under
the two policies. Count choice/probe overhead as well as implementation and
measurement. Report time/tokens to a predeclared valid performance target and
final valid performance within budget; keep failures and missing usage explicit.
Repeated trials and other workloads are required for a general efficacy claim.

The gate enforces recording **before evaluation**, with instructions to record
before editing. A plugin cannot prove that external edits were not already made,
that the Agent genuinely considered alternatives, or that its estimates were
well founded. The feature establishes an auditable connection, not a causal
improvement in optimization efficiency. Its software tests cover both CLI paths,
stale/missing/tampered receipts and an optimistic forecast whose candidate fails.
Fresh Agent efficacy comparisons and noise-aware promotion remain separate work.
