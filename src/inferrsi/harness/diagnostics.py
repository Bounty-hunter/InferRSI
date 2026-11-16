"""Retain advisory diagnostic facts; never grade or promote an implementation."""

import json
import math
import os
import shlex
import shutil
import time
import uuid

from ..infra.artifacts import atomic_write_json, sha256
from . import candidates


def prepare(root, plan, state, *, command, question, if_supported, if_rejected, timeout,
            inputs=()):
    for text in (question, if_supported, if_rejected):
        if not isinstance(text, str) or not text.strip() or len(text) > 4096:
            raise ValueError("Diagnostic question and next actions must be nonempty, bounded text")
    if if_supported.strip() == if_rejected.strip():
        raise ValueError("Diagnostic outcomes must lead to different next actions")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Diagnostic timeout must be finite and positive")
    argv = shlex.split(command)
    if not argv or len(command) > 16384:
        raise ValueError("Supply bounded diagnostic argv, not a shell command")
    if len(inputs) > 32 or len({os.path.normcase(p.name) for p in inputs}) != len(inputs):
        raise ValueError("Diagnostic inputs require up to 32 unique file names")
    for path in inputs:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Diagnostic inputs must be regular files within 8 MiB each")
    relative = "diagnostics/attempt-" + uuid.uuid4().hex
    directory = root / relative
    directory.mkdir(parents=True)
    (directory / "output").mkdir()
    identity = candidates.retain(root / state["best"]["path"],
                                 directory / plan["candidate_name"])
    values = {"candidate": str(directory / plan["candidate_name"]),
              "baseline": str(root / plan["baseline_path"]), "task": str(root / "frozen"),
              "output": str(directory / "output"), "python": plan["python"]}
    input_identities = {}
    for path in inputs:
        destination = directory / "inputs" / path.name
        destination.parent.mkdir(exist_ok=True)
        destination.write_bytes(path.read_bytes())
        shutil.copymode(path, destination)
        input_identities[destination.relative_to(directory).as_posix()] = sha256(destination)
        values["input:" + path.name] = str(destination)
    for key, value in values.items():
        argv = [arg.replace("{" + key + "}", value) for arg in argv]
    if any("{input:" in arg for arg in argv):
        raise ValueError("Diagnostic command references an undeclared --input file")
    return {"kind": "diagnostic", "path": relative, "question": question,
            "if_supported": if_supported, "if_rejected": if_rejected,
            "basis_sha256": identity, "command": argv,
            "input_identities": input_identities,
            "deadline": min(state["deadline"] - plan["final_reserve_seconds"],
                            time.time() + timeout), "started_at": time.time()}


def settle(root, plan, pending, execution):
    directory = root / pending["path"]
    if candidates.identity(directory / plan["candidate_name"]) != pending["basis_sha256"]:
        raise ValueError("Diagnostic changed the retained input")
    for name, expected in pending["input_identities"].items():
        if sha256(directory / name) != expected:
            raise ValueError("Diagnostic changed a retained script/input")
    evidence = {}
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("Diagnostic artifacts cannot contain symbolic links")
        if path.is_file() and path != directory / "observation.json":
            evidence[path.relative_to(directory).as_posix()] = sha256(path)
    # Only a recorded normal process exit allows further work. Timeouts or a
    # coordinator failure do not establish cleanup of external device leases.
    settled = (execution.get("status") in ("completed", "failed")
               and type(execution.get("returncode")) is int
               and not execution.get("coordinator_error")
               and not (directory / "coordinator-error.json").exists())
    record = {**pending, "status": execution.get("status"), "execution": execution,
              "elapsed_seconds": execution.get("elapsed_seconds"), "evidence_files": evidence,
              "effect": "advisory_only_not_task_acceptance", "execution_settled": settled}
    atomic_write_json(directory / "observation.json", record)
    record["observation_sha256"] = sha256(directory / "observation.json")
    return record


def verify(root, record):
    directory = root / record["path"]
    if sha256(directory / "observation.json") != record["observation_sha256"]:
        raise ValueError("Retained diagnostic observation changed")
    observed = json.loads((directory / "observation.json").read_text(encoding="utf-8"))
    paths = list(directory.rglob("*"))
    if directory.is_symlink() or any(path.is_symlink() for path in paths):
        raise ValueError("Retained diagnostic evidence contains symbolic links")
    actual = {p.relative_to(directory).as_posix() for p in paths if p.is_file()}
    if actual != set(observed["evidence_files"]) | {"observation.json"}:
        raise ValueError("Retained diagnostic evidence file set changed")
    for name, expected in observed["evidence_files"].items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or sha256(path) != expected:
            raise ValueError("Retained diagnostic evidence changed")
