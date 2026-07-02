"""Generate reviewable KiCad schematic projects from compiled Design IR."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.export.kicad import export_kicad_schematic
from zaptrace.generation.compiler import CompiledDesignIR

SchematicArtifactKind = Literal["project", "schematic"]


class GeneratedSchematicArtifact(BaseModel):
    """One generated KiCad schematic-project artifact."""

    model_config = ConfigDict(strict=False)

    kind: SchematicArtifactKind
    path: str
    sha256: str
    size_bytes: int = Field(ge=0)


class GeneratedKiCadSchematicReport(BaseModel):
    """Evidence report for a generated KiCad schematic project."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    design_name: str
    family_id: str
    output_dir: str
    passed: bool
    generated_files: list[GeneratedSchematicArtifact]
    requirement_trace_count: int = Field(ge=0)
    provenance_record_count: int = Field(ge=0)
    non_claims: list[str] = Field(default_factory=list)
    claim_violations: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class GeneratedKiCadSchematicProject(BaseModel):
    """Generated KiCad schematic-project files and evidence report."""

    model_config = ConfigDict(strict=False, arbitrary_types_allowed=True)

    project_path: Path
    schematic_path: Path
    report_path: Path
    report: GeneratedKiCadSchematicReport


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _artifact(kind: SchematicArtifactKind, path: Path, root: Path) -> GeneratedSchematicArtifact:
    return GeneratedSchematicArtifact(
        kind=kind,
        path=_relative(path, root),
        sha256=_sha256(path),
        size_bytes=path.stat().st_size,
    )


def _has_unsafe_claim(text: str, claim: str) -> bool:
    positive = claim in text
    dashed_non_claim = f"not-{claim}" in text
    spaced_non_claim = f"not {claim}" in text
    return positive and not dashed_non_claim and not spaced_non_claim


def _claim_violations(paths: list[Path]) -> list[str]:
    """Return generated files that contain unsafe fabrication/production claims."""
    violations: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8").lower()
        if _has_unsafe_claim(text, "fabrication-ready") or _has_unsafe_claim(text, "production-ready"):
            violations.append(path.name)
    return sorted(violations)


def generated_kicad_schematic_report_json(report: GeneratedKiCadSchematicReport) -> str:
    """Serialize a generated schematic report as stable JSON."""
    return json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def generate_kicad_schematic_project(
    compiled: CompiledDesignIR,
    output_dir: str | Path,
) -> GeneratedKiCadSchematicProject:
    """Generate a reviewable KiCad schematic project from compiled Design IR.

    This emits `.kicad_pro`, `.kicad_sch`, and a machine-readable evidence report.
    It does not claim the generated project is fabrication-ready.
    """
    out = Path(output_dir)
    files = export_kicad_schematic(compiled.design, out)
    project_path = files["project"]
    schematic_path = files["schematic"]
    generated_paths = [project_path, schematic_path]
    claim_violations = _claim_violations(generated_paths)
    report = GeneratedKiCadSchematicReport(
        design_name=compiled.design.meta.name,
        family_id=compiled.report.family_id,
        output_dir=".",
        passed=not claim_violations,
        generated_files=[
            _artifact("project", project_path, out),
            _artifact("schematic", schematic_path, out),
        ],
        requirement_trace_count=len(compiled.report.requirement_traces),
        provenance_record_count=len(compiled.design.prov_records),
        non_claims=compiled.report.non_claims,
        claim_violations=claim_violations,
    )
    report_path = out / f"{compiled.design.meta.name}.kicad_schematic_generation.json"
    report_path.write_text(generated_kicad_schematic_report_json(report), encoding="utf-8")
    return GeneratedKiCadSchematicProject(
        project_path=project_path,
        schematic_path=schematic_path,
        report_path=report_path,
        report=report,
    )
