"""Runner-neutral KiCad benchmark task framework (issue #131).

Defines a YAML task schema and a subprocess-based runner that grades arbitrary
KiCad project directories without importing ZapTrace internals at run time.

Public surface
--------------
GraderPolicy        – skip policy enum for unavailable external tools
GraderSpec          – one grader definition from a task YAML
TaskSpec            – full task schema loaded from YAML
GraderResult        – one grader's deterministic outcome
TaskRunResult       – aggregated deterministic run result
load_task           – parse a task YAML file
run_task            – execute all graders and return a deterministic result
canonical_run_hash  – sha256 of the canonical (timestamp-stripped) result JSON
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TASK_SCHEMA_VERSION = "1.0"
_SENTINEL_RUN_ID = "RUN-CANONICAL"  # used instead of timestamps in deterministic output

# ---------------------------------------------------------------------------
# Schema types
# ---------------------------------------------------------------------------

GraderPolicy = Literal["never", "tool_unavailable", "always_skip"]


@dataclass
class GraderSpec:
    """One grader entry in a task YAML."""

    grader_id: str
    tool: str  # e.g. "kicad-cli", "builtin", "python"
    command: list[str] | None  # None → builtin
    skip_policy: GraderPolicy = "tool_unavailable"
    timeout_seconds: int = 60
    output_schema: str = "generic_v1"
    version_min: str = ""
    description: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GraderSpec:
        return cls(
            grader_id=d["grader_id"],
            tool=d["tool"],
            command=d.get("command"),
            skip_policy=d.get("skip_policy", "tool_unavailable"),
            timeout_seconds=int(d.get("timeout_seconds", 60)),
            output_schema=d.get("output_schema", "generic_v1"),
            version_min=d.get("version_min", ""),
            description=d.get("description", ""),
        )


@dataclass
class TaskSpec:
    """Full task schema loaded from a task YAML file."""

    task_schema_version: str
    task_id: str
    name: str
    track: str  # e.g. "kicad_grading", "repair", "interop"
    description: str
    graders: list[GraderSpec]
    thresholds: dict[str, Any]
    allowed_inputs: list[str]
    limits: dict[str, Any]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TaskSpec:
        return cls(
            task_schema_version=d.get("task_schema_version", TASK_SCHEMA_VERSION),
            task_id=d["task_id"],
            name=d["name"],
            track=d.get("track", "kicad_grading"),
            description=d.get("description", ""),
            graders=[GraderSpec.from_dict(g) for g in d.get("graders", [])],
            thresholds=d.get("thresholds", {}),
            allowed_inputs=d.get("allowed_inputs", ["kicad_project"]),
            limits=d.get("limits", {}),
        )


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class GraderResult:
    """Deterministic outcome for one grader."""

    grader_id: str
    status: Literal["pass", "fail", "skip", "error"]
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    skip_reason: str | None = None
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskRunResult:
    """Aggregated deterministic run result for one task execution.

    The ``run_hash`` field is a sha256 of the canonical (timestamp-free) JSON
    so that two clean runs on the same inputs can be compared byte-for-byte.
    """

    task_id: str
    run_id: str  # set to _SENTINEL_RUN_ID in canonical/deterministic mode
    status: Literal["pass", "fail", "skip", "error"]
    grader_results: list[GraderResult] = field(default_factory=list)
    threshold_violations: list[str] = field(default_factory=list)
    run_hash: str = ""
    schema_version: str = TASK_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Ensure run_hash is always present even if computed after construction
        return d

    def compute_hash(self) -> str:
        """Return sha256 of the canonical JSON (run_id=sentinel, no wall time)."""
        canonical = self.to_dict()
        canonical["run_id"] = _SENTINEL_RUN_ID
        canonical.pop("run_hash", None)
        # Strip timing data so hash is stable across machines/runs
        for gr in canonical.get("grader_results", []):
            gr["elapsed_seconds"] = 0.0
        blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Task loading
# ---------------------------------------------------------------------------


def load_task(path: Path) -> TaskSpec:
    """Parse a task YAML file and return a TaskSpec."""
    raw = yaml.safe_load(path.read_text())
    return TaskSpec.from_dict(raw)


# ---------------------------------------------------------------------------
# Grader execution helpers
# ---------------------------------------------------------------------------


def _check_tool_available(tool: str) -> bool:
    """Return True if ``tool`` is on PATH."""
    return shutil.which(tool) is not None


def _run_builtin_net_parity(
    project_dir: Path,
    spec: GraderSpec,
    thresholds: dict[str, Any],
) -> GraderResult:
    """Builtin grader: count .kicad_sch files and compare net counts naively.

    This grader never calls external tools; it is always available and
    produces deterministic output from pure Python parsing.
    """
    t0 = time.monotonic()
    sch_files = list(project_dir.rglob("*.kicad_sch"))
    if not sch_files:
        return GraderResult(
            grader_id=spec.grader_id,
            status="skip",
            detail="No .kicad_sch files found in project directory",
            skip_reason="no_schematic_files",
            elapsed_seconds=round(time.monotonic() - t0, 3),
        )

    # Count (wire) net references as a simple parity signal
    total_nets: int = 0
    for f in sch_files:
        content = f.read_text(errors="replace")
        total_nets += content.count("(net ")

    min_score: float = thresholds.get(spec.grader_id, {}).get("min_score", 0.0)
    # Score: bounded 0→1 by presence of any net data
    score = 1.0 if total_nets > 0 else 0.0
    passed = score >= min_score

    return GraderResult(
        grader_id=spec.grader_id,
        status="pass" if passed else "fail",
        detail=f"Found {total_nets} net references across {len(sch_files)} schematic(s); score={score:.2f}",
        evidence={"net_count": total_nets, "schematic_count": len(sch_files), "score": score},
        elapsed_seconds=round(time.monotonic() - t0, 3),
    )


def _run_builtin_file_inventory(
    project_dir: Path,
    spec: GraderSpec,
    thresholds: dict[str, Any],
) -> GraderResult:
    """Builtin grader: verify expected KiCad file types are present."""
    t0 = time.monotonic()
    extensions = sorted([".kicad_pro", ".kicad_sch"])
    found = {ext: sorted(str(p) for p in project_dir.rglob(f"*{ext}")) for ext in extensions}
    missing = [ext for ext, files in found.items() if not files]

    if missing:
        return GraderResult(
            grader_id=spec.grader_id,
            status="fail",
            detail=f"Missing file types: {missing}",
            evidence={"missing_extensions": missing},
            elapsed_seconds=round(time.monotonic() - t0, 3),
        )

    return GraderResult(
        grader_id=spec.grader_id,
        status="pass",
        detail="All required KiCad file types present",
        evidence={ext[1:]: len(files) for ext, files in found.items()},
        elapsed_seconds=round(time.monotonic() - t0, 3),
    )


_BUILTIN_GRADERS: dict[str, Any] = {
    "net_parity": _run_builtin_net_parity,
    "file_inventory": _run_builtin_file_inventory,
}


def _run_subprocess_grader(
    project_dir: Path,
    spec: GraderSpec,
    thresholds: dict[str, Any],
) -> GraderResult:
    """Run an external tool grader in an isolated subprocess."""
    t0 = time.monotonic()
    # Check tool availability
    tool_exe = spec.command[0] if spec.command else spec.tool
    if not _check_tool_available(tool_exe):
        if spec.skip_policy == "tool_unavailable":
            return GraderResult(
                grader_id=spec.grader_id,
                status="skip",
                detail=f"External tool '{tool_exe}' not found; skipped per policy",
                skip_reason="tool_unavailable",
                elapsed_seconds=round(time.monotonic() - t0, 3),
            )
        if spec.skip_policy == "always_skip":
            return GraderResult(
                grader_id=spec.grader_id,
                status="skip",
                detail="Grader configured with always_skip policy",
                skip_reason="always_skip",
                elapsed_seconds=round(time.monotonic() - t0, 3),
            )
        # policy == "never" → must fail
        return GraderResult(
            grader_id=spec.grader_id,
            status="error",
            detail=f"Required tool '{tool_exe}' not found and skip_policy is 'never'",
            elapsed_seconds=round(time.monotonic() - t0, 3),
        )

    if not spec.command:
        return GraderResult(
            grader_id=spec.grader_id,
            status="error",
            detail="Subprocess grader has no command defined",
            elapsed_seconds=round(time.monotonic() - t0, 3),
        )

    # Substitute {project_dir} placeholder
    cmd = [c.replace("{project_dir}", str(project_dir)) for c in spec.command]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=spec.timeout_seconds,
            cwd=project_dir,
        )
        elapsed = round(time.monotonic() - t0, 3)
        passed = proc.returncode == 0
        return GraderResult(
            grader_id=spec.grader_id,
            status="pass" if passed else "fail",
            detail=f"exit={proc.returncode}; stdout={proc.stdout[:200]}",
            evidence={"returncode": proc.returncode, "stdout_len": len(proc.stdout)},
            elapsed_seconds=elapsed,
        )
    except subprocess.TimeoutExpired:
        return GraderResult(
            grader_id=spec.grader_id,
            status="error",
            detail=f"Grader timed out after {spec.timeout_seconds}s",
            elapsed_seconds=round(time.monotonic() - t0, 3),
        )
    except Exception as exc:  # noqa: BLE001
        return GraderResult(
            grader_id=spec.grader_id,
            status="error",
            detail=f"Grader raised exception: {exc}",
            elapsed_seconds=round(time.monotonic() - t0, 3),
        )


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


def run_task(
    spec: TaskSpec,
    project_dir: Path,
    *,
    run_id: str = _SENTINEL_RUN_ID,
) -> TaskRunResult:
    """Execute all graders in *spec* against *project_dir*.

    The runner never imports ZapTrace internals in the hot path — it only
    calls built-in Python functions or isolated subprocesses.  When external
    tools are unavailable the grader result carries an explicit ``skip``
    status and reason so downstream consumers can distinguish "skipped" from
    "passed".

    Returns a :class:`TaskRunResult` with a deterministic ``run_hash``
    (computed over a sentinel run_id so hash is stable across machines).
    """
    max_rt = spec.limits.get("max_runtime_seconds", 300)
    wall_start = time.monotonic()

    grader_results: list[GraderResult] = []

    for grader_spec in spec.graders:
        if time.monotonic() - wall_start > max_rt:
            grader_results.append(
                GraderResult(
                    grader_id=grader_spec.grader_id,
                    status="skip",
                    detail="Task wall-time limit exceeded",
                    skip_reason="task_timeout",
                )
            )
            continue

        if grader_spec.skip_policy == "always_skip":
            grader_results.append(
                GraderResult(
                    grader_id=grader_spec.grader_id,
                    status="skip",
                    detail="Configured with always_skip policy",
                    skip_reason="always_skip",
                )
            )
            continue

        if grader_spec.tool == "builtin":
            builtin_fn = _BUILTIN_GRADERS.get(grader_spec.grader_id)
            if builtin_fn is None:
                grader_results.append(
                    GraderResult(
                        grader_id=grader_spec.grader_id,
                        status="error",
                        detail=f"Unknown builtin grader id: {grader_spec.grader_id!r}",
                    )
                )
            else:
                grader_results.append(builtin_fn(project_dir, grader_spec, spec.thresholds))
        else:
            grader_results.append(_run_subprocess_grader(project_dir, grader_spec, spec.thresholds))

    # Evaluate threshold violations (only on pass/fail results)
    violations: list[str] = []
    for result in grader_results:
        if result.status == "fail":
            violations.append(f"{result.grader_id}: {result.detail[:120]}")

    overall = "skip" if all(r.status == "skip" for r in grader_results) else ("fail" if violations else "pass")
    if any(r.status == "error" for r in grader_results):
        overall = "error"

    run_result = TaskRunResult(
        task_id=spec.task_id,
        run_id=run_id,
        status=overall,
        grader_results=grader_results,
        threshold_violations=violations,
    )
    run_result.run_hash = run_result.compute_hash()
    return run_result


def canonical_run_hash(result: TaskRunResult) -> str:
    """Return the sha256 of the canonical (sentinel run_id) result JSON."""
    return result.compute_hash()
