"""CLI commands for Proof Pack management."""

from __future__ import annotations

from pathlib import Path

import click

from zaptrace.cli.output import console, print_summary, print_table
from zaptrace.proof import ProofPack, run_proof, validate_proof_pack


@click.group()
def proof() -> None:
    """Manage and run Proof Packs."""


@proof.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--verbose", "-v", is_flag=True, help="Show detailed check output")
@click.option("--format", "-f", "output_format", type=click.Choice(["text", "json"]), default="text")
@click.option("--output", "-o", type=click.Path(), default=None, help="Write report to file")
def run(path: str, verbose: bool, output_format: str, output: str | None) -> None:
    """Run a Proof Pack against a design.

    PATH can be a proof.yaml file or a directory containing proof.yaml.
    """
    try:
        pack = run_proof(path)

        if output_format == "json":
            report = pack.report_json()
            if output:
                Path(output).write_text(report)
                print_summary(True, f"Proof report written to {output}")
            else:
                console.print(report)
            return

        # Text output
        console.print(pack.summary)

        if verbose and pack.results:
            console.print("\n[bold]Details:[/]")
            for r in pack.results:
                status_icon = "✓" if r.passed else "✗"
                status_style = "green" if r.passed else "red"
                console.print(f"  [{status_style}]{status_icon}[/] {r.check.name}: {r.message}")
                if r.details:
                    import json as _json

                    console.print(f"    {_json.dumps(r.details, indent=4)}")

        if not pack.passed:
            raise SystemExit(1)

    except FileNotFoundError as e:
        print_summary(False, str(e))
        raise click.Abort() from e
    except Exception as e:
        print_summary(False, f"Proof pack failed: {e}")
        raise click.Abort() from e


@proof.command()
@click.argument("path", type=click.Path(exists=True))
def list(path: str) -> None:  # noqa: A001
    """List all checks in a Proof Pack without running them."""
    try:
        path_obj = Path(path)
        if path_obj.is_dir():
            path_obj = path_obj / "proof.yaml"
        pack = ProofPack.load(path_obj)

        if not pack.manifest.checks:
            print_summary(False, "No checks defined in proof pack")
            return

        print_table(
            f"Proof Pack: {pack.manifest.name}",
            columns=["Name", "Type", "Severity", "Description"],
            rows=[
                [
                    c.name,
                    c.type,
                    c.severity.value,
                    c.description[:50] if c.description else "",
                ]
                for c in pack.manifest.checks
            ],
        )
    except Exception as e:
        print_summary(False, str(e))
        raise click.Abort() from e


@proof.command()
@click.argument("path", type=click.Path(exists=True))
def info(path: str) -> None:
    """Show proof pack metadata."""
    try:
        path_obj = Path(path)
        if path_obj.is_dir():
            path_obj = path_obj / "proof.yaml"
        pack = ProofPack.load(path_obj)
        m = pack.manifest

        console.print(f"[bold]Name:[/] {m.name}")
        console.print(f"[bold]Version:[/] {m.version}")
        console.print(f"[bold]Description:[/] {m.description or '(none)'}")
        console.print(f"[bold]Design:[/] {m.design_path}")
        console.print(f"[bold]Author:[/] {m.author or '(unknown)'}")
        console.print(f"[bold]Checks:[/] {len(m.checks)}")
        console.print(f"[bold]References:[/] {len(m.references)}")
        console.print(f"[bold]Tags:[/] {', '.join(m.tags) if m.tags else '(none)'}")
        console.print(f"[bold]Requires:[/] {', '.join(m.requires) if m.requires else '(none)'}")

        console.print("\n[bold]Constraints:[/]")
        console.print(f"  Min clearance: {m.model.min_clearance_mm}mm")
        console.print(f"  Min trace width: {m.model.min_trace_width_mm}mm")
        console.print(f"  Min annular ring: {m.model.min_annular_ring_mm}mm")
        console.print(f"  Max layers: {m.model.max_layer_count}")
        console.print(f"  Allowed layers: {m.model.allowed_layer_counts}")

    except Exception as e:
        print_summary(False, str(e))
        raise click.Abort() from e


@proof.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--strict", is_flag=True, help="Exit non-zero on warnings, not just errors")
def validate(path: str, strict: bool) -> None:
    """Validate a proof pack manifest and its artifacts.

    PATH can be a proof.yaml file, a .proof.zip bundle, or a directory.

    Checks schema conformance, artifact existence, SHA-256 hashes,
    check record integrity, and the human-review limitation warning.
    """
    try:
        target = Path(path)
        base = Path(".")

        if target.suffix == ".zip":
            pack = ProofPack.load(target)
            manifest = pack.manifest
            base = target.parent
        elif target.is_dir():
            p = target / "proof.yaml"
            if not p.exists():
                print_summary(False, f"No proof.yaml found in {target}")
                raise click.Abort()
            pack = ProofPack.load(p)
            manifest = pack.manifest
            base = target
        else:
            pack = ProofPack.load(target)
            manifest = pack.manifest
            base = target.parent

        errors = validate_proof_pack(manifest, base)
        if not errors:
            print_summary(True, "Proof pack is valid.")
            return

        console.print("[red]Validation errors:[/]")
        for e in errors:
            console.print(f"  - {e}")

        n_fail = sum(1 for e in errors if "missing" in e.lower() or "mismatch" in e.lower() or "required" in e.lower())

        if strict:
            raise SystemExit(1)
        if n_fail > 0:
            raise SystemExit(1)

    except click.Abort:
        raise
    except Exception as e:
        print_summary(False, f"Validation failed: {e}")
        raise click.Abort() from e
