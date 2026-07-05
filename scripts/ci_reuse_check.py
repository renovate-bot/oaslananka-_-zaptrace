#!/usr/bin/env python3
"""REUSE/SPDX compliance gate for ZapTrace.

Runs ``reuse lint`` and reports compliance status. Exits 0 on success,
1 on failure. Designed for CI use.

Usage::

    uv run python scripts/ci_reuse_check.py [--strict]

Options:
    --strict    Fail on warnings in addition to errors (default: errors only).

Policy summary
--------------
* All source files (``*.py``, ``*.rs``, ``*.yaml``, config files, …) must be
  covered by SPDX licensing information.
* Bulk coverage is declared in ``.reuse/dep5`` to avoid adding boilerplate to
  auto-generated files and test fixtures.
* New hand-authored source files SHOULD carry inline SPDX headers:

      .. code-block:: python

          # SPDX-FileCopyrightText: 2026 Osman Aslan (oaslananka)
          # SPDX-License-Identifier: MIT

* The following file categories are exempt from inline header requirements and
  are instead covered by the ``.reuse/dep5`` bulk declaration:
    - ``data/library/**/*.yaml``  — generated library part entries
    - ``tests/fixtures/**``       — synthetic test fixtures
    - ``*.lock``                  — auto-generated lock files
    - ``rust/target/**``          — Rust build artefacts
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def _run_reuse_lint() -> tuple[int, str]:
    """Run ``reuse lint`` and return (exit_code, output)."""
    try:
        result = subprocess.run(
            ["reuse", "lint"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode, result.stdout + result.stderr
    except FileNotFoundError:
        return 1, ("ERROR: 'reuse' not found. Install via: pip install reuse\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="REUSE/SPDX compliance gate for ZapTrace.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on warnings in addition to errors.",
    )
    args = parser.parse_args(argv)

    print("Running REUSE/SPDX compliance check …")
    code, output = _run_reuse_lint()

    print(output)

    if code != 0:
        print(
            "FAIL: Project is not REUSE-compliant.\n"
            "Fix by adding 'SPDX-FileCopyrightText' and "
            "'SPDX-License-Identifier' to the files listed above, or "
            "add a bulk entry to .reuse/dep5.\n"
            "See: https://reuse.software/tutorial/"
        )
        return 1

    if args.strict and "RECOMMENDATIONS" in output:
        print("FAIL: Warnings detected (--strict mode).")
        return 1

    print("PASS: Project is REUSE-compliant.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
