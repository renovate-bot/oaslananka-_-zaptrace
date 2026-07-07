"""CI script: benchmark score reproducibility from a clean clone (issue #133).

Runs the benchmark tasks defined in benchmarks/ against their fixtures and
compares the resulting run hashes against a committed reference file.  Any
divergence is reported with the first failing task/hash pair.

Usage:
    # Generate/update reference hashes:
    python scripts/ci_benchmark_reproduce.py --update-reference

    # Verify hashes match reference:
    python scripts/ci_benchmark_reproduce.py

The reference file lives at docs/reports/benchmark-reproduce-reference.json.
All nondeterministic fields (wall time, run timestamps) are normalised to
sentinel values before hashing so the hash is stable across machines.

Exit codes:
    0  All hashes match the reference (or --update-reference was used).
    1  One or more hashes diverge from the reference.
    2  Reference file does not exist (run with --update-reference first).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

# Ensure repo root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from zaptrace.benchmark.interop_track import load_interop_task, run_interop_task
from zaptrace.benchmark.kicad_task import load_task, run_task
from zaptrace.benchmark.repair_track import load_repair_task, run_repair_task

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_REFERENCE_FILE = _REPO_ROOT / "docs" / "reports" / "benchmark-reproduce-reference.json"
_CORPUS_DIR = _REPO_ROOT / "tests" / "corpus" / "kicad"

_BENCHMARK_DIRS = [
    ("kicad_grading", _REPO_ROOT / "benchmarks" / "kicad-task-v1" / "task.yaml"),
    ("repair", _REPO_ROOT / "benchmarks" / "repair-track-v1" / "task.yaml"),
    ("interop", _REPO_ROOT / "benchmarks" / "interop-track-v1" / "task.yaml"),
]

_INTEROP_EVIDENCE = _REPO_ROOT / "benchmarks" / "interop-track-v1" / "evidence-battery-charger.yaml"


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def _resolve_reference_cli_path(raw: Path) -> Path:
    candidate = raw if raw.is_absolute() else _REPO_ROOT / raw
    resolved = candidate.resolve(strict=False)
    parent = resolved.parent.resolve(strict=False)
    allowed_roots = (_REPO_ROOT.resolve(strict=True), Path(tempfile.gettempdir()).resolve(strict=True))
    if not any(_is_relative_to(parent, allowed) for allowed in allowed_roots):
        raise ValueError("Reference path is outside allowed roots")
    return resolved


# ---------------------------------------------------------------------------
# Hash collection
# ---------------------------------------------------------------------------


def _collect_hashes() -> dict[str, str]:
    """Run all benchmark tasks and return {task_key: run_hash} mapping.

    All hashes use sentinel run_id so they are stable across machines.
    """
    hashes: dict[str, str] = {}

    for track, task_path in _BENCHMARK_DIRS:
        if not task_path.exists():
            print(f"  SKIP  {task_path.name} (not found)", file=sys.stderr)
            continue

        if track == "kicad_grading":
            spec = load_task(task_path)
            # Run against each corpus project if available
            project_dirs = sorted(_CORPUS_DIR.iterdir()) if _CORPUS_DIR.is_dir() else []
            if not project_dirs:
                # Run against a minimal synthetic input (empty dir = all skip)
                import tempfile

                with tempfile.TemporaryDirectory() as td:
                    result = run_task(spec, Path(td), external_tool_mode="canonical_skip")
                key = f"{track}/{spec.task_id}/__synthetic__"
                hashes[key] = result.run_hash
            else:
                for proj in project_dirs:
                    if proj.is_dir():
                        result = run_task(spec, proj, external_tool_mode="canonical_skip")
                        key = f"{track}/{spec.task_id}/{proj.name}"
                        hashes[key] = result.run_hash

        elif track == "repair":
            spec_r = load_repair_task(task_path)
            project_dirs = sorted(_CORPUS_DIR.iterdir()) if _CORPUS_DIR.is_dir() else []
            if not project_dirs:
                import tempfile

                with tempfile.TemporaryDirectory() as td:
                    result_r = run_repair_task(spec_r, Path(td))
                key = f"{track}/{spec_r.task_id}/__synthetic__"
                hashes[key] = result_r.run_hash
            else:
                for proj in project_dirs:
                    if proj.is_dir():
                        result_r = run_repair_task(spec_r, proj)
                        key = f"{track}/{spec_r.task_id}/{proj.name}"
                        hashes[key] = result_r.run_hash

        elif track == "interop":
            spec_i = load_interop_task(task_path)
            result_i = run_interop_task(spec_i, _INTEROP_EVIDENCE)
            key = f"{track}/{spec_i.task_id}/evidence-battery-charger"
            hashes[key] = result_i.run_hash

    return hashes


# ---------------------------------------------------------------------------
# Reference file helpers
# ---------------------------------------------------------------------------

_REFERENCE_SCHEMA_VERSION = "1.0"


def _load_reference(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return data.get("hashes", {})


def _save_reference(hashes: dict[str, str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": _REFERENCE_SCHEMA_VERSION,
        "description": (
            "Canonical benchmark run hashes for reproducibility verification. "
            "Generated by scripts/ci_benchmark_reproduce.py --update-reference. "
            "Nondeterministic fields (run_id, wall time) are normalised to sentinel values."
        ),
        "hashes": hashes,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(f"Reference updated: {path} ({len(hashes)} entries)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark reproducibility CI gate")
    parser.add_argument(
        "--update-reference",
        action="store_true",
        help="Regenerate the reference hash file instead of verifying",
    )
    parser.add_argument(
        "--reference-file",
        type=Path,
        default=_REFERENCE_FILE,
        help="Path to the reference JSON file",
    )
    args = parser.parse_args()
    reference_file = _resolve_reference_cli_path(args.reference_file)

    print("Collecting benchmark run hashes...")
    current = _collect_hashes()
    print(f"  Collected {len(current)} hash(es)")

    if args.update_reference:
        _save_reference(current, reference_file)
        sys.exit(0)

    reference = _load_reference(reference_file)
    if reference is None:
        print(
            f"ERROR: Reference file not found: {reference_file}\nRun with --update-reference to generate it.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Compare
    diverged: list[tuple[str, str, str]] = []  # (key, reference_hash, current_hash)
    for key, ref_hash in sorted(reference.items()):
        cur_hash = current.get(key)
        if cur_hash is None:
            print(f"  MISSING  {key}: present in reference, absent in current run")
            diverged.append((key, ref_hash, "<missing>"))
        elif cur_hash != ref_hash:
            print(f"  DIVERGED {key}:")
            print(f"    reference: {ref_hash}")
            print(f"    current:   {cur_hash}")
            diverged.append((key, ref_hash, cur_hash))
        else:
            print(f"  OK       {key}: {cur_hash[:12]}...")

    # New keys not in reference
    for key, cur_hash in sorted(current.items()):
        if key not in reference:
            print(f"  NEW      {key}: {cur_hash[:12]}... (not in reference; run --update-reference)")

    if diverged:
        print(f"\nFAIL: {len(diverged)} hash(es) diverged from reference")
        print(f"First divergence: {diverged[0][0]}")
        sys.exit(1)

    print(f"\nOK: All {len(reference)} reference hash(es) match")
    sys.exit(0)


if __name__ == "__main__":
    main()
