"""Explainable experiment allocation; source structure is a lead, never a gain oracle."""

import ast
import hashlib
import math
import statistics
from pathlib import Path

KINDS = ("eliminate_work", "fuse", "replace", "tune", "repair")


def configuration(name, *, stall_limit=None, action_seconds=None, exploration_seconds=None):
    if name == "agent":
        return {"name": name}
    if name != "framework":
        raise ValueError("Unknown experiment selection policy")
    if type(stall_limit) is not int or stall_limit < 1:
        raise ValueError("Framework selection requires an explicit positive stall limit")
    for value in (action_seconds, exploration_seconds):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError("Framework selection requires positive action/exploration time")
    return {"name": name, "stall_limit": stall_limit,
            "action_seconds": action_seconds, "exploration_seconds": exploration_seconds}


def validate_pool(payload, basis):
    if not isinstance(payload, dict) or set(payload) != {"basis_sha256", "proposals"}:
        raise ValueError("Proposals require basis_sha256 and proposals")
    if payload["basis_sha256"] != basis:
        raise ValueError("Proposal basis is not the retained current best")
    proposals = payload["proposals"]
    if not isinstance(proposals, list) or not 1 <= len(proposals) <= 16:
        raise ValueError("Provide between one and sixteen distinct proposals")
    identities = set()
    for proposal in proposals:
        if not isinstance(proposal, dict) or set(proposal) != {
                "id", "family", "target", "kind", "hypothesis"}:
            raise ValueError("Each proposal requires id, family, target, kind and hypothesis")
        for key in ("id", "family", "target", "hypothesis"):
            value = proposal[key]
            if not isinstance(value, str) or not value.strip() or len(value) > 4096:
                raise ValueError(f"Proposal {key} must be bounded nonempty text")
        if proposal["id"] in identities or proposal["kind"] not in KINDS:
            raise ValueError("Proposal IDs must be distinct and kinds must be supported")
        identities.add(proposal["id"])
    return proposals


def source_facts(source: Path, includes=None):
    """Inspect Python call/loop structure without importing or executing candidate code.

    A target is a symbol (single file), or path.py::symbol (directory). A call's
    lexical loop depth can under/overestimate runtime work. It cannot veto code.
    """
    from .candidates import members

    paths = [source] if source.is_file() else list(members(source, includes).values())
    if len(paths) > 128 or sum(p.stat().st_size for p in paths) > 8 * 1024 * 1024:
        return {}  # Missing structural evidence must leave proposals eligible.
    facts = {}
    for path in paths:
        if path.suffix != ".py" or path.stat().st_size > 1024 * 1024:
            continue
        prefix = "" if source.is_file() else path.relative_to(source).as_posix() + "::"
        try:
            tree = ast.parse(path.read_bytes())
        except (SyntaxError, UnicodeError):
            continue
        if sum(1 for _ in ast.walk(tree)) > 50000:
            continue
        scopes, calls = {}, []

        class Visitor(ast.NodeVisitor):
            scope = "<module>"
            depth = 0

            def visit_FunctionDef(self, node):
                previous, depth = self.scope, self.depth
                self.scope, self.depth = node.name, 0
                scopes[node.name] = hashlib.sha256(ast.dump(node).encode()).hexdigest()
                self.generic_visit(node)
                self.scope, self.depth = previous, depth

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_For(self, node):
                self.depth += 1
                self.generic_visit(node)
                self.depth -= 1

            visit_AsyncFor = visit_For
            visit_While = visit_For

            def visit_Call(self, node):
                name = ast.unparse(node.func)
                calls.append((self.scope, name, self.depth))
                self.generic_visit(node)

        Visitor().visit(tree)
        if len(scopes) > 256 or len(calls) > 4096:
            continue
        inherited = {name: 0 for name in scopes}
        # A bounded propagation is enough for a structural hint; cap recursive paths.
        for _ in range(len(scopes)):
            updated = dict(inherited)
            for caller, callee, depth in calls:
                if callee in scopes:
                    updated[callee] = min(4, max(updated[callee],
                                               inherited.get(caller, 0) + depth))
            if updated == inherited:
                break
            inherited = updated
        for name, fingerprint in scopes.items():
            local = [(callee, depth) for caller, callee, depth in calls if caller == name]
            facts[prefix + name] = {
                "target_sha256": fingerprint, "calls": len(local),
                "repeat_depth": max([inherited[name], *[
                    min(4, inherited[name] + depth) for _, depth in local]]),
                "source": "static_call_loop_structure", "latency_headroom": None,
            }
    return facts


def rank(proposals, facts, rounds, config):
    """Produce a deterministic partial-priority order; unknown work stays eligible.

    Kind is the Agent's declared mechanism, not a verified performance fact.
    We use it only as a soft search heuristic. Only measured results can promote.
    """
    ranked = []
    for proposal in proposals:
        fact = facts.get(proposal["target"])
        related = []
        for record in rounds:
            decision = record.get("search_decision")
            if not decision:
                continue
            previous = decision["proposal"]
            if (previous["family"], previous["target"]) != (
                    proposal["family"], proposal["target"]):
                continue
            if fact and decision.get("target_sha256") != fact["target_sha256"]:
                continue  # a changed target invalidates this local-stall inference
            related.append(record)
        stalled = 0
        for record in reversed(related):
            if record.get("promoted"):
                break
            if record["assessment"]["status"] != "infrastructure_failure":
                stalled += 1
        durations = [r.get("search_decision", {}).get("action_elapsed_seconds")
                     for r in related]
        durations = [v for v in durations if type(v) in (int, float) and v > 0]
        cost = statistics.median(durations) if durations else config["action_seconds"]
        repeating = bool(fact and fact["repeat_depth"] > 0)
        # Work removal in repeated scope, then fusion/replacement, then local tuning.
        # These are explicit heuristics, not learned probabilities or E2E forecasts.
        tier = (0 if repeating and proposal["kind"] == "eliminate_work" else
                1 if repeating and proposal["kind"] in ("fuse", "replace") else 2)
        deferred = stalled >= config["stall_limit"]
        reasons = ["target_present" if fact else "target_unknown_not_rejected"]
        if repeating:
            reasons.append("repeated_source_scope_not_measured_latency")
        if deferred:
            reasons.append("local_nonpromotion_limit_reached")
        row = {"proposal": proposal, "target_sha256": fact["target_sha256"] if fact else None,
               "signals": {"source": fact, "family_attempts": len(related),
                           "nonpromoting_streak": stalled, "estimated_seconds": cost,
                           "cost_source": "observed_action_median" if durations else "budget_proxy",
                           "predicted_gain": None},
               "deferred": deferred, "reasons": reasons,
               "priority": [int(deferred), tier, len(related), cost,
                            -(fact["repeat_depth"] if fact else 0), proposal["id"]]}
        ranked.append(row)
    return sorted(ranked, key=lambda item: item["priority"])


def guidance():
    return (
        "Before editing, register a short pool with propose (basis_sha256 and proposals). "
        "Each proposal has id, family, target, kind and hypothesis. Kinds: "
        + ", ".join(KINDS) + ". Targets are Python symbols, or relative.py::symbol for projects. "
        "Use select: the framework chooses an action and returns its decision_id and retained "
        "basis. Restore that basis before implementation. Submit round with --decision-id. "
        "Declare honest mechanism/target metadata; static structure is a lead, not proof of gain. "
        "Keep distinct mechanisms when useful; do not fabricate alternatives to fill a quota. "
        "A deferred proposal needs new evidence/changed conditions, or select --proposal-id "
        "with --explore-reason within the frozen exploration budget. Exact source repeats "
        "require an explicit exploration reason; final always retests independently. "
        "Diagnostics remain optional, must change a decision, and consume the same budget."
    )
