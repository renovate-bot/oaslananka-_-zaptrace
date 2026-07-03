"""Check DCO sign-offs for pull requests that modify code-sensitive files."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

CODE_SUFFIXES = {
    ".py",
    ".rs",
    ".yml",
    ".yaml",
    ".toml",
    ".lock",
    ".sh",
    ".ps1",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
}

CODE_NAMES = {
    "Dockerfile",
    "docker-compose.yml",
    "Taskfile.yml",
    "pyproject.toml",
    "uv.lock",
    "Cargo.toml",
    "Cargo.lock",
}

SIGNED_OFF_BY_RE = re.compile(r"(?im)^Signed-off-by:\s+.+\s+<[^@<>\s]+@[^<>\s]+>$")


def is_code_sensitive_path(path: str) -> bool:
    p = Path(path)
    if p.name in CODE_NAMES:
        return True
    if p.suffix in CODE_SUFFIXES:
        return True
    if path.startswith(".github/workflows/"):
        return True
    return path.startswith("scripts/") and p.suffix in {".py", ".sh"}


def run_git(args: list[str]) -> str:
    completed = subprocess.run(["git", *args], check=True, text=True, capture_output=True)
    return completed.stdout


def changed_paths(base: str, head: str) -> list[str]:
    output = run_git(["diff", "--name-only", "--diff-filter=ACMR", f"{base}..{head}"])
    return [line.strip() for line in output.splitlines() if line.strip()]


def commit_messages(base: str, head: str) -> list[str]:
    output = run_git(["log", "--format=%B%x00", f"{base}..{head}"])
    return [message.strip() for message in output.split("\x00") if message.strip()]


def has_signoff(message: str) -> bool:
    return bool(SIGNED_OFF_BY_RE.search(message))


def check_dco(base: str, head: str) -> tuple[bool, str]:
    paths = changed_paths(base, head)
    code_paths = [path for path in paths if is_code_sensitive_path(path)]
    if not code_paths:
        return True, "DCO check skipped: no code-sensitive files changed."

    messages = commit_messages(base, head)
    missing = [idx + 1 for idx, message in enumerate(messages) if not has_signoff(message)]
    if missing:
        return (
            False,
            "DCO check failed: code-sensitive files changed but commit message(s) "
            f"{missing} do not include a Signed-off-by line. Changed code-sensitive paths: " + ", ".join(code_paths),
        )
    return True, f"DCO check passed for {len(messages)} commit(s) touching {len(code_paths)} code-sensitive path(s)."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check DCO sign-offs for code-sensitive pull request changes")
    parser.add_argument("--base", required=True, help="Base git ref")
    parser.add_argument("--head", default="HEAD", help="Head git ref")
    args = parser.parse_args(argv)

    ok, message = check_dco(args.base, args.head)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
