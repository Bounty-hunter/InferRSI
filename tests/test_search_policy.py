"""Structural heuristics and empirical deferral never invent performance evidence."""

from inferrsi.harness.search_policy import configuration, rank, source_facts


def test_repetition_is_soft_priority_and_changed_target_invalidates_stall(tmp_path):
    source = tmp_path / "candidate.py"
    source.write_text("def helper(x):\n    return x + 1\n"
                      "def compute(x):\n    for _ in range(4):\n        helper(x)\n")
    facts = source_facts(source)
    assert facts["helper"]["repeat_depth"] == 1
    config = configuration("framework", stall_limit=1, action_seconds=60,
                           exploration_seconds=30)
    proposals = [{"id": name, "family": name, "target": target, "kind": kind,
                  "hypothesis": "Check a proposed mechanism"}
                 for name, target, kind in (("tune", "compute", "tune"),
                                            ("reuse", "compute", "eliminate_work"),
                                            ("unknown", "absent", "replace"))]
    ranked = rank(proposals, facts, [], config)
    assert ranked[0]["proposal"]["id"] == "reuse"
    assert all(row["signals"]["predicted_gain"] is None for row in ranked)
    rounds = [{"search_decision": {**ranked[0], "action_elapsed_seconds": 20},
               "promoted": False, "assessment": {"status": "completed"}}]
    ranked = rank(proposals, facts, rounds, config)
    assert ranked[-1]["proposal"]["id"] == "reuse" and ranked[-1]["deferred"]
    assert ranked[-1]["signals"]["estimated_seconds"] == 20
    source.write_text(source.read_text().replace("range(4)", "range(2)"))
    ranked = rank(proposals, source_facts(source), rounds, config)
    assert ranked[0]["proposal"]["id"] == "reuse" and not ranked[0]["deferred"]
    assert not next(r for r in ranked if r["proposal"]["id"] == "unknown")["deferred"]
