"""CI gate: runner-neutral KiCad benchmark task (issue #131).

Loads every ``task.yaml`` found under ``benchmarks/kicad-task-v1/``, runs all
graders against the corpus fixtures in ``tests/corpus/kicad/``, and exits
non-zero if any grader returns ``fail`` or ``error``.  ``skip`` results are
reported but do not fail the gate.

Usage:
    python scripts/ci_kicad_task_runner.py [--task-dir TASK_DIR] [--project-dir PROJECT_DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure repo root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from zaptrace.benchmark.kicad_task import TaskRunResult, load_task, run_task


def _run_gate(task_dir: Path, project_dir: Path) -> int:
    """Run the gate; return exit code (0=pass, 1=fail)."""
    task_files = sorted(task_dir.glob("task.yaml"))
    if not task_files:
        print(f"ERROR: no task.yaml found under {task_dir}", file=sys.stderr)
        return 1

    project_dirs = [d for d in project_dir.iterdir() if d.is_dir()] if project_dir.is_dir() else []
    if not project_dirs:
        print(f"WARNING: no subdirectories found in {project_dir}; running against parent")
        project_dirs = [project_dir]

    all_results: list[TaskRunResult] = []
    failed = False

    for task_path in task_files:
        spec = load_task(task_path)
        print(f"\n=== Task: {spec.task_id} ({spec.name}) ===")
        print(f"    Track: {spec.track} | Graders: {len(spec.graders)}")

        for proj in project_dirs:
            result = run_task(spec, proj)
            all_results.append(result)

            icon = {"pass": "✓", "fail": "✗", "skip": "⊘", "error": "!"}.get(result.status, "?")
            print(f"  [{icon}] {proj.name}: {result.status.upper()} (hash={result.run_hash[:12]})")
            for gr in result.grader_results:
                gi = {"pass": " ✓", "fail": " ✗", "skip": " ⊘", "error": " !"}.get(gr.status, " ?")
                print(f"      {gi} {gr.grader_id}: {gr.detail[:80]}")

            if result.status in ("fail", "error"):
                failed = True
                for v in result.threshold_violations:
                    print(f"      VIOLATION: {v}")

    print(f"\n{'=' * 60}")
    print(f"Total task runs: {len(all_results)}")
    print(f"  pass={sum(1 for r in all_results if r.status == 'pass')}")
    print(f"  fail={sum(1 for r in all_results if r.status == 'fail')}")
    print(f"  skip={sum(1 for r in all_results if r.status == 'skip')}")
    print(f"  error={sum(1 for r in all_results if r.status == 'error')}")

    return 1 if failed else 0


def main() -> None:
    repo_root = Path(__file__).parent.parent
    parser = argparse.ArgumentParser(description="KiCad benchmark task runner CI gate")
    parser.add_argument(
        "--task-dir",
        type=Path,
        default=repo_root / "benchmarks" / "kicad-task-v1",
        help="Directory containing task.yaml files",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=repo_root / "tests" / "corpus" / "kicad",
        help="Directory containing KiCad project subdirectories",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write JSON results",
    )
    args = parser.parse_args()

    rc = _run_gate(args.task_dir, args.project_dir)

    if args.json_out:
        # Write a simple summary
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        summary = {"task_dir": str(args.task_dir), "project_dir": str(args.project_dir), "exit_code": rc}
        args.json_out.write_text(json.dumps(summary, indent=2))

    sys.exit(rc)


if __name__ == "__main__":
    main()
