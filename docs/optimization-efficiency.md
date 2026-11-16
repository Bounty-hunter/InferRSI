# Budget-aware optimization experiments

This is an experimental, opt-in Harness policy. Its objective is better **measured,
valid whole-task performance within a budget**, or less cost to reach a fixed
performance target. Forecasts are optional evidence, not the objective or an
acceptance gate. Neither this implementation nor its software tests establish
an efficiency improvement.

## Current implementation

Start an ordinary campaign or packaged task with `--decision-policy efficient`.
The default `agent` and the existing `recorded` policy retain their behavior.
Both ordinary projects and packaged tasks use the same controller.

The efficient policy supplies concise operational guidance and `search_context`
on each status/round response: recent attempts including failures, evidence
references, diagnostic questions/outcomes, and observed command time. Full raw
observations remain on disk. The Agent still chooses; Harness does not infer
optimal priorities from strings or certify its reasoning.

A normal round needs only `--hypothesis`. `propose` and numerical estimates are
optional. If used, recorded proposals retain their existing integrity checks;
an explicitly pending probe proposal still needs a revised implementation
proposal before a round. No new decision schema or learned ranker is introduced.

Use existing evidence when its source and workload assumptions still apply.
Refresh profiling when the bottleneck may have changed. Knowledge addresses a
specific missing fact; retrieval rank is not optimization priority. Explicit
`knowledge --reuse <retained-context-path>` returns the pinned bytes already
delivered to this campaign, without a new query. It never silently caches a
mutable query, and is rejected when knowledge is disabled.

## Bounded diagnostics

Use a diagnostic only if the result could change the next action and the check
is cheaper than proceeding directly. This operation executes real argv through
the same executor and frozen allocator prefix as the campaign:

```bash
inferrsi campaign diagnose --session <campaign> \
  --question 'Does the native API support the required input layout?' \
  --if-supported 'Implement and run the fixed full-task protocol' \
  --if-rejected 'Investigate a different implementation' \
  --input <probe.py> \
  --command '"{python}" "{input:probe.py}" --candidate "{candidate}" --output "{output}"' \
  --timeout-seconds <diagnostic-budget>
```

Packaged tasks expose the same `benchmarks session diagnose` operation. The argv
placeholders are `{python}`, `{candidate}` (a retained copy of the current best),
`{baseline}`, `{task}` (frozen resources), `{output}` and `{result}`. `{result}`
points to the executor's JSON result path; output JSON is optional and advisory.
Scripts may put traces and other files in `{output}`. Do not modify input copies.
`--input` retains explicitly declared files and executes their snapshot when
referenced through `{input:filename}`. Names must be unique. `{output}` already
exists; Qwen's `profile_workload.py` requires a new `--output-dir`, so use
`{output}/profile` for that tool.

The timeout includes allocator waiting. It is capped by the remaining search
deadline, preserving the final reserve. The operation uses the frozen allocator
prefix; do not nest another allocator inside the command. No diagnostic starts
after search rounds or time are exhausted. It consumes total time, but no formal
candidate round. Agent reasoning/tool tokens must still be collected from the host.

Diagnostic records retain the question, two caller-declared next actions, command,
source snapshot, logs, outputs, elapsed time and hashes. Normal process exits,
including a nonzero diagnostic exit, return control to the Agent. A timeout,
cancel, unknown execution failure or integrity change blocks further work;
process exit must not be used to invent external lease cleanup. Interrupted
settlement can collect an existing execution receipt with `recover`, never
relaunch it. If execution evidence is missing, recovery refuses.

This is not a sandbox or an automatic dependency freezer. Undeclared external
scripts/libraries and device allocation must be pinned by the experiment. The
source identity is the bound input copy; it does not prove a script actually
used it. Diagnostic output, reduced-shape timing and exit zero never establish
task correctness, promote a candidate, or replace full evaluation and final.

## Formal rounds and failures

Quality checks, sampling, promotion and independent final remain unchanged.
Packaged tasks now accept `--round-mode up_to` as an explicit option; `exact`
remains the default. An early final requires at least one round and a stop reason.
Do not stop merely because the first passing candidate was found.

Qwen's worker distinguishes explicit Python invocation/known attention-mask
argument errors from unknown device faults. Only the former are candidate
failures that permit repair and continued search. Generic ACL/tiling/driver
failures are not reclassified as incorrect code. Any experiment comparison must
give both policies this same evaluator change.

## Evidence and evaluation plan

1. Audit cost distribution and comparable archived candidates. Do not rank
   accumulated revisions as if they were alternatives from the same parent.
2. Blind candidate ranking can test measurement selection; it cannot demonstrate
   savings in implementing ideas. Include a simple rule and direct-Agent choice
   as controls, and account for missed fast candidates and prediction cost.
3. Compare original `agent` and `efficient` on the same runtime, model, knowledge
   snapshot, quality protocol and budget. Use fresh sessions and repeat paired
   trajectories before a general efficacy claim. Freeze parameters before search.
4. Report independent final, completion rate, best measured performance versus
   elapsed time and cumulative tokens, and cost to predeclared targets. Include
   analysis, retrieval, diagnostics, failed attempts and final. Separate cached
   tokens; missing usage is unknown. Command wall time can include queueing and
   is not device compute time. It does not include external Agent reasoning.
5. Maintain opt-in if gains are absent or uncertain. Only then broaden to other
   tasks and the policy-by-knowledge on/off comparison.

## Method references

- [Cost-aware Bayesian optimization](https://papers.nips.cc/paper_files/paper/2012/hash/05311655a15b75fab86956663e1819cd-Abstract.html):
  consider improvement and experiment duration together. No GP or calibrated
  probability model is implemented here.
- [PerfAgent](https://arxiv.org/html/2607.19653v1): targeted profiler feedback,
  iterative refinement and validation. Its gains do not prove the marginal
  benefit of this policy atop an already iterative RSI workflow.
- [GPU Forecasters](https://arxiv.org/html/2605.31464v1): rank generated candidate
  implementations before expensive device measurement. Equal measurement budget
  is not equal total generation/prediction cost; this remains a later extension.
