"""Standalone implementations of all registered agent tools.

Each tool is a standalone function with typed parameters.
Tools share a common signature pattern: (session_id, **params) -> dict.
"""

from __future__ import annotations

import copy
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import zaptrace.erc.rules as _erc_rules  # noqa: N812
from zaptrace.core.diff import DiffType, diff_designs
from zaptrace.core.models import Component
from zaptrace.core.parser import parse_file, parse_str
from zaptrace.core.session_store import make_design_mapping
from zaptrace.core.state import design_state_hash
from zaptrace.erc.models import ERCResult
from zaptrace.erc.patches import suggest_patches
from zaptrace.erc.runner import ERCRunner
from zaptrace.export.bom import generate_bom_csv, generate_bom_json
from zaptrace.export.kicad import export_kicad_schematic
from zaptrace.export.report import generate_report
from zaptrace.export.spice import export_spice_netlist
from zaptrace.export.svg import render_schematic_svg
from zaptrace.library.loader import LibraryLoader
from zaptrace.pipeline.autopilot import Autopilot, PipelineContext, PipelineStage
from zaptrace.security.policy import required_tool_capability
from zaptrace.synthesis.calculators import (
    buck_inductor_capacitor,
    decoupling_plan,
    divider_for_output,
    e_series_ceil,
    e_series_floor,
    i2c_pullup,
    led_series_resistor,
    lipo_charge_resistor,
    nearest_e_series,
    rc_cutoff_hz,
    usb_c_cc_termination,
)
from zaptrace.synthesis.engine import list_templates, synthesize_with_provenance

# Shared state (per-session). In production this would be a proper session store.
_sessions: dict[str, dict[str, Any]] = {}
_library: LibraryLoader | None = None
_WORKSPACE: Path | None = None


def _get_workspace() -> Path:
    """Return the sandboxed workspace root.

    Respects *ZAPTRACE_WORKSPACE* env var; falls back to the current
    working directory.  The workspace is resolved once per process.
    """
    global _WORKSPACE
    if _WORKSPACE is None:
        raw = os.environ.get("ZAPTRACE_WORKSPACE", "")
        _WORKSPACE = Path(raw).resolve() if raw else Path.cwd().resolve()
    return _WORKSPACE


def _validate_path(path: str | Path, must_exist: bool = False) -> Path:
    """Validate that *path* is inside the sandboxed workspace.

    Raises ``ValueError`` (user-facing) on:
      - Absolute paths outside the workspace root.
      - Relative paths that escape the workspace via ``..`` segments.
      - Symlinks that resolve outside the workspace (when *must_exist*).
      - Non-existent files (when *must_exist*).

    Returns the resolved absolute ``Path``.
    """
    p = Path(path)
    workspace = _get_workspace()
    try:
        resolved = p.resolve(strict=must_exist)
    except (FileNotFoundError, RuntimeError):
        if must_exist:
            raise ValueError(f"Path not found: {path}") from None
        resolved = p.resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError:
        raise ValueError(f"Path outside workspace: {path}") from None
    return resolved


def _get_autopilot() -> Autopilot:
    return Autopilot()


def _get_library() -> LibraryLoader:
    global _library
    if _library is None:
        _library = LibraryLoader()
    return _library


def _get_session(session_id: str) -> dict[str, Any]:
    if session_id not in _sessions:
        _sessions[session_id] = {"designs": make_design_mapping(session_id)}
    return _sessions[session_id]


def _persist_design(session: dict[str, Any], design_name: str) -> None:
    designs = session.get("designs", {})
    persist = getattr(designs, "persist", None)
    if callable(persist):
        persist(design_name)


def _record_validation_status(session: dict[str, Any], design_name: str) -> dict[str, Any]:
    """Store validation evidence tied to the current design state hash."""
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")

    erc = session.get("erc_results", {}).get(design_name)
    drc = session.get("drc_results", {}).get(design_name)
    status: dict[str, Any] = {
        "design_state_hash": design_state_hash(design),
        "erc": None,
        "drc": None,
    }
    if erc is not None:
        status["erc"] = {
            "passed": bool(erc.passed),
            "total_errors": erc.total_errors,
            "total_warnings": erc.total_warnings,
            "total_info": erc.total_info,
        }
    if drc is not None:
        status["drc"] = {
            "passed": bool(drc.passed),
            "total_violations": drc.total_violations,
        }
    session.setdefault("validation_status", {})[design_name] = status
    return status


def _require_release_gate(session: dict[str, Any], design_name: str, approval_id: str | None) -> dict[str, Any]:
    """Require a fresh validation status and explicit approval for release exports.

    Release-capability authorization says who may request an export. This gate
    says whether this specific design state is safe enough to emit fabrication
    or assembly artifacts. It fails closed until ERC has passed for the current
    state and a non-empty external approval identifier is supplied.
    """
    if not approval_id or not approval_id.strip():
        raise ValueError("approval_id is required for release-export operations")

    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")

    validation = session.get("validation_status", {}).get(design_name)
    current_hash = design_state_hash(design)
    if validation is None:
        raise ValueError(
            f"Release export for '{design_name}' requires a fresh validation status. Run erc_validate first."
        )
    if validation.get("design_state_hash") != current_hash:
        raise ValueError(f"Release export for '{design_name}' requires fresh validation for the current design state")

    erc = validation.get("erc")
    if not erc or not erc.get("passed"):
        raise ValueError(f"Release export for '{design_name}' requires passing ERC validation")

    drc = validation.get("drc")
    if drc is not None and not drc.get("passed"):
        raise ValueError(f"Release export for '{design_name}' requires passing DRC validation when DRC has been run")

    gate = {"approval_id": approval_id.strip(), "validation": validation}
    session.setdefault("release_approvals", {})[design_name] = gate
    return gate


# ---------------------------------------------------------------------------
# Tool 1 — design_parse_file
# ---------------------------------------------------------------------------


def tool_design_parse_file(path: str, session_id: str = "default") -> dict[str, Any]:
    """Parse a design YAML file into a Design object."""
    p = _validate_path(path, must_exist=True)
    design = parse_file(p)
    session = _get_session(session_id)
    session["designs"][design.meta.name] = design
    return {
        "design_name": design.meta.name,
        "component_count": len(design.components),
        "net_count": len(design.nets),
        "board": f"{design.board.width_mm}x{design.board.height_mm}mm",
    }


# ---------------------------------------------------------------------------
# Tool 2 — design_parse_str
# ---------------------------------------------------------------------------


def tool_design_parse_str(yaml_content: str, session_id: str = "default") -> dict[str, Any]:
    """Parse a YAML string into a Design object."""
    design = parse_str(yaml_content)
    session = _get_session(session_id)
    session["designs"][design.meta.name] = design
    return {
        "design_name": design.meta.name,
        "component_count": len(design.components),
        "net_count": len(design.nets),
        "board": f"{design.board.width_mm}x{design.board.height_mm}mm",
    }


# ---------------------------------------------------------------------------
# Tool 3 — design_inspect
# ---------------------------------------------------------------------------


def tool_design_inspect(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Inspect a parsed design and return its details."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        available = list(session.get("designs", {}).keys())
        raise ValueError(f"Design '{design_name}' not found. Available: {available}")
    return design.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Tool 4 — design_list_nets
# ---------------------------------------------------------------------------


def tool_design_list_nets(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """List all nets in a design with their connections."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    nets_info: dict[str, dict[str, Any]] = {}
    for net_id, net in design.nets.items():
        nets_info[net_id] = {
            "name": net.name,
            "type": net.type.value,
            "nodes": [{"component": n.component_ref, "pin": n.pin_name} for n in net.nodes],
        }
    return {"design": design_name, "nets": nets_info}


# ---------------------------------------------------------------------------
# Tool 5 — synthesize_design
# ---------------------------------------------------------------------------


def tool_synthesize_design(intent: str, session_id: str = "default") -> dict[str, Any]:
    """Select the best-matching pre-built template for an intent (template selection).

    This is not from-scratch circuit synthesis: no topology or component values
    are generated. The returned ``selection`` records which template was loaded.
    """
    design, selection = synthesize_with_provenance(intent)
    session = _get_session(session_id)
    session["designs"][design.meta.name] = design
    return {
        "design_name": design.meta.name,
        "component_count": len(design.components),
        "net_count": len(design.nets),
        "description": design.meta.description,
        "method": selection.method,
        "selection": {
            "template_id": selection.template_id,
            "template_name": selection.template_name,
            "match_score": selection.match_score,
        },
        "note": (
            "Loaded the closest pre-built template by keyword match; this is "
            "template selection, not from-scratch circuit synthesis."
        ),
    }


# ---------------------------------------------------------------------------
# Tool 6 — list_synthesis_templates
# ---------------------------------------------------------------------------


def tool_list_synthesis_templates() -> list[dict[str, str]]:
    """List available synthesis templates."""
    return list_templates()


# ---------------------------------------------------------------------------
# Tool 7 — erc_validate
# ---------------------------------------------------------------------------


def tool_erc_validate(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Run all ERC rules on a design."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    runner = ERCRunner()
    result = runner.run(design)
    session["erc_results"] = {**session.get("erc_results", {}), design_name: result}
    validation = _record_validation_status(session, design_name)
    return {
        "design": design_name,
        "passed": result.passed,
        "validation_status": validation,
        "total_errors": result.total_errors,
        "total_warnings": result.total_warnings,
        "total_info": result.total_info,
        "coverage_summary": result.coverage_summary(),
        "categories_covered": result.categories_covered,
        "checks_run": [
            {
                "rule_id": c.rule_id,
                "title": c.title,
                "category": c.category,
                "violation_count": c.violation_count,
            }
            for c in result.checks_run
        ],
        "coverage_gaps": result.coverage_gaps,
        "violations": [
            {
                "rule_id": v.rule_id,
                "severity": v.severity.value,
                "message": v.message,
                "components": v.component_refs,
                "nets": v.net_refs,
            }
            for v in result.violations
        ],
    }


# ---------------------------------------------------------------------------
# Tool 8 — erc_get_result
# ---------------------------------------------------------------------------


def tool_erc_get_result(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Get the latest ERC result for a design."""
    session = _get_session(session_id)
    result: ERCResult | None = session.get("erc_results", {}).get(design_name)
    if result is None:
        raise ValueError(f"No ERC result for '{design_name}'. Run erc_validate first.")
    return {
        "design": design_name,
        "passed": result.passed,
        "total_errors": result.total_errors,
        "total_warnings": result.total_warnings,
        "total_info": result.total_info,
        "violation_count": len(result.violations),
        "coverage_summary": result.coverage_summary(),
        "categories_covered": result.categories_covered,
        "coverage_gaps": result.coverage_gaps,
    }


# ---------------------------------------------------------------------------
# Tool 9 — erc_list_rules
# ---------------------------------------------------------------------------


def tool_erc_list_rules() -> dict[str, Any]:
    """List all registered ERC rules with descriptions."""
    import inspect

    rules_info: list[dict[str, str]] = []
    for name, obj in inspect.getmembers(_erc_rules, inspect.isfunction):
        if name.startswith("rule_ERC"):
            doc = (obj.__doc__ or "No description").strip()
            rules_info.append(
                {
                    "id": name.replace("rule_", ""),
                    "description": doc.split("\n")[0],
                }
            )
    rules_info.sort(key=lambda x: x["id"])
    return {"rules": rules_info}


# ---------------------------------------------------------------------------
# Tool 10 — place_components
# ---------------------------------------------------------------------------


def tool_place_components(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Place all components on the board using grid + force-directed layout."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    from zaptrace.algo.placer import place_components as _place

    positions = _place(design)
    session["positions"] = {**session.get("positions", {}), design_name: positions}
    return {
        "design": design_name,
        "component_count": len(positions),
        "positions": {k: list(v) for k, v in positions.items()},
    }


# ---------------------------------------------------------------------------
# Tool 11 — route_nets
# ---------------------------------------------------------------------------


def tool_route_nets(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Route all nets using Manhattan MST routing."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    positions = session.get("positions", {}).get(design_name)
    from zaptrace.algo.router import route_nets as _route

    result = _route(design, positions or {})
    session["routing"] = {**session.get("routing", {}), design_name: result}
    return {
        "design": design_name,
        "routed_nets": result.routed_nets,
        "total_nets": result.total_nets,
        "coverage_pct": result.coverage_pct,
        "unrouted": result.unrouted_nets,
        "segment_count": len(result.segments),
    }


# ---------------------------------------------------------------------------
# Tool 12 — library_search
# ---------------------------------------------------------------------------


def tool_library_search(query: str, max_results: int = 10) -> dict[str, Any]:
    """Search the component library by keyword."""
    lib = _get_library()
    results = lib.search(query, max_results=max_results)
    return {
        "query": query,
        "count": len(results),
        "results": [
            {
                "id": r.id,
                "name": r.name,
                "category": r.category,
                "manufacturer": r.manufacturer,
                "mpn": r.mpn,
                "description": r.description,
                "package": r.package,
                "confidence_score": r.confidence_score,
                "confidence_grade": r.confidence_grade,
            }
            for r in results
        ],
    }


# ---------------------------------------------------------------------------
# Tool 13 — library_get
# ---------------------------------------------------------------------------


def tool_library_get(component_id: str) -> dict[str, Any]:
    """Get full details for a specific library component."""
    lib = _get_library()
    spec = lib.get(component_id)
    return {
        "id": spec.id,
        "name": spec.name,
        "category": spec.category,
        "manufacturer": spec.manufacturer,
        "mpn": spec.mpn,
        "description": spec.description,
        "datasheet": spec.datasheet,
        "package": spec.package,
        "footprint": spec.footprint,
        "lifecycle": spec.lifecycle,
        "voltage_supply": spec.voltage_supply,
        "pins": spec.pins,
        "properties": spec.properties,
        "confidence_score": spec.confidence_score,
        "confidence_grade": spec.confidence_grade,
        "missing_metadata": spec.missing_metadata,
    }


# ---------------------------------------------------------------------------
# Tool 14 — library_list_categories
# ---------------------------------------------------------------------------


def tool_library_list_categories() -> dict[str, Any]:
    """List all component library categories."""
    lib = _get_library()
    return {"categories": lib.list_categories()}


# ---------------------------------------------------------------------------
# Tool 15 — export_bom_csv
# ---------------------------------------------------------------------------


def tool_export_bom_csv(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Generate Bill of Materials as CSV."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    csv_str = generate_bom_csv(design)
    return {"csv": csv_str, "design": design_name}


# ---------------------------------------------------------------------------
# Tool 16 — export_bom_json
# ---------------------------------------------------------------------------


def tool_export_bom_json(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Generate Bill of Materials as JSON."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    json_str = generate_bom_json(design)
    return {"json": json_str, "design": design_name}


# ---------------------------------------------------------------------------
# Tool 17 — export_report
# ---------------------------------------------------------------------------


def tool_export_report(design_name: str, output_path: str | None = None, session_id: str = "default") -> dict[str, Any]:
    """Generate a comprehensive Markdown design report."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    erc_result = session.get("erc_results", {}).get(design_name)
    report = generate_report(design, erc_result=erc_result)
    if output_path:
        out = _validate_path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
    return {"report": report, "design": design_name}


# ---------------------------------------------------------------------------
# Tool 18 — export_svg
# ---------------------------------------------------------------------------


def tool_export_svg(design_name: str, output_path: str | None = None, session_id: str = "default") -> dict[str, Any]:
    """Render a schematic overview as SVG."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    positions = session.get("positions", {}).get(design_name)
    svg = render_schematic_svg(design, positions=positions)
    if output_path:
        out = _validate_path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(svg, encoding="utf-8")
    return {"svg": svg, "design": design_name}


# ---------------------------------------------------------------------------
# Tool 19 — export_kicad
# ---------------------------------------------------------------------------


def tool_export_kicad(
    design_name: str,
    output_dir: str,
    approval_id: str | None = None,
    session_id: str = "default",
) -> dict[str, Any]:
    """Export to KiCad schematic + PCB format."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    out = _validate_path(output_dir)
    release_gate = _require_release_gate(session, design_name, approval_id)
    files = export_kicad_schematic(design, out)
    return {
        "design": design_name,
        "output_dir": str(out),
        "files": {k: str(v) for k, v in files.items()},
        "release_gate": release_gate,
    }


# ---------------------------------------------------------------------------
# Tool 20 — kicad_import_project
# ---------------------------------------------------------------------------


def tool_kicad_import_project(
    project_path: str,
    session_id: str = "default",
) -> dict[str, Any]:
    """Import a KiCad project (hierarchical or flat) into the session.

    Accepts a project directory or ``.kicad_pro`` / ``.kicad_sch`` file path.
    Returns design identity, sheet hierarchy, parity results, and degradation
    evidence. The imported design is stored in the session under the project
    name.

    Parameters
    ----------
    project_path:
        Workspace-relative or absolute path to a KiCad project directory,
        ``.kicad_pro`` file, or ``.kicad_sch`` file.
    session_id:
        Session identifier (default: ``"default"``).

    Returns
    -------
    dict
        ``design_name`` — name of the imported design (also stored in session);
        ``component_count`` — number of flattened components;
        ``net_count`` — number of flattened nets;
        ``sheet_count`` — number of schematic sheets discovered;
        ``net_score`` — fraction of nets with at least one connection (0–1);
        ``error_count`` — count of error-severity findings;
        ``warning_count`` — count of warning-severity findings;
        ``findings`` — ordered list of cross-validation and degradation findings;
        ``sheets`` — sheet hierarchy (sheet_id, name, parent_id, component_ids).
    """
    from zaptrace.kicad.project_importer import import_kicad_project

    path = _validate_path(project_path, must_exist=True)
    result = import_kicad_project(path)

    session = _get_session(session_id)
    design_name = result.design.meta.name or path.stem
    session.setdefault("designs", {})[design_name] = result.design

    return {
        "design_name": design_name,
        "component_count": len(result.design.components),
        "net_count": len(result.design.nets),
        "sheet_count": len(result.sheets),
        "net_score": result.net_score,
        "error_count": result.error_count,
        "warning_count": result.warning_count,
        "findings": [f.to_dict() for f in result.findings],
        "sheets": [
            {
                "sheet_id": s.sheet_id,
                "name": s.name,
                "parent_id": s.parent_id,
                "component_count": len(s.component_ids),
            }
            for s in result.sheets
        ],
    }


# ---------------------------------------------------------------------------
# Tool 21 — design_diff
# ---------------------------------------------------------------------------


def tool_design_diff(design_a_name: str, design_b_name: str, session_id: str = "default") -> dict[str, Any]:
    """Diff two designs and report changes."""

    session = _get_session(session_id)
    designs = session.get("designs", {})
    design_a = designs.get(design_a_name)
    design_b = designs.get(design_b_name)
    if design_a is None:
        raise ValueError(f"Design '{design_a_name}' not found")
    if design_b is None:
        raise ValueError(f"Design '{design_b_name}' not found")
    entries = diff_designs(design_a, design_b)
    added = [e for e in entries if e.type in (DiffType.COMPONENT_ADDED, DiffType.NET_ADDED)]
    removed = [e for e in entries if e.type in (DiffType.COMPONENT_REMOVED, DiffType.NET_REMOVED)]
    changed = [
        e for e in entries if e.type in (DiffType.VALUE_CHANGED, DiffType.FOOTPRINT_CHANGED, DiffType.BOARD_CHANGED)
    ]  # noqa: E501
    return {
        "design_a": design_a_name,
        "design_b": design_b_name,
        "diff_entries": [e.__dict__ for e in entries],
        "added_count": len(added),
        "removed_count": len(removed),
        "changed_count": len(changed),
        "summary": f"{len(added)} added, {len(removed)} removed, {len(changed)} changed",
    }


# ---------------------------------------------------------------------------
# Tool 22 — pipeline_run
# ---------------------------------------------------------------------------


def tool_pipeline_run(
    source: str | None = None, intent: str | None = None, output_dir: str | None = None, session_id: str = "default"
) -> dict[str, Any]:  # noqa: E501
    """Run the full design pipeline from file or intent."""
    out_dir = _validate_path(output_dir) if output_dir else None
    autopilot = Autopilot(output_dir=out_dir) if out_dir else _get_autopilot()
    if source:
        src = _validate_path(source, must_exist=True)
        ctx = autopilot.run_from_file(src)
    elif intent:
        ctx = autopilot.run_from_intent(intent)
    else:
        raise ValueError("Provide either 'source' (file path) or 'intent' (synthesis)")
    session = _get_session(session_id)
    if ctx.design:
        session["designs"][ctx.design.meta.name] = ctx.design
    if ctx.design and ctx.erc_result:
        session["erc_results"] = {
            **session.get("erc_results", {}),
            ctx.design.meta.name: ctx.erc_result,
        }
    return {
        "stages_completed": len(ctx.results),
        "all_successful": ctx.all_successful,
        "duration_seconds": round(ctx.duration, 2),
        "stages": {s.value: {"success": r.success, "error": r.error} for s, r in ctx.results.items()},
    }


# ---------------------------------------------------------------------------
# Tool 22 — pipeline_run_stage
# ---------------------------------------------------------------------------


def tool_pipeline_run_stage(
    stage: str,
    source: str | None = None,
    intent: str | None = None,
    design_name: str | None = None,
    output_dir: str | None = None,
    session_id: str = "default",
) -> dict[str, Any]:  # noqa: E501
    """Run a single pipeline stage."""
    out_dir = _validate_path(output_dir) if output_dir else None
    autopilot = Autopilot(output_dir=out_dir) if out_dir else _get_autopilot()
    stage_enum = PipelineStage(stage)
    ctx = PipelineContext(output_dir=autopilot._output_dir)

    if design_name:
        session = _get_session(session_id)
        ctx.design = session.get("designs", {}).get(design_name)
    elif source:
        ctx.source = str(_validate_path(source, must_exist=True))
    elif intent:
        ctx.source = intent
    else:
        raise ValueError("Provide one of: design_name, source, intent")

    ctx = autopilot.run_stage(ctx, stage_enum)
    result = ctx.results.get(stage_enum)
    if result is None:
        raise RuntimeError(f"Stage {stage} did not produce a result")
    return {
        "stage": stage,
        "success": result.success,
        "error": result.error,
        "duration_ms": result.duration_ms,
    }


# ---------------------------------------------------------------------------
# Tool 23 — pipeline_status
# ---------------------------------------------------------------------------


def tool_pipeline_status(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Get pipeline processing status for a design."""
    session = _get_session(session_id)
    has_design = design_name in session.get("designs", {})
    has_erc = design_name in session.get("erc_results", {})
    has_positions = design_name in session.get("positions", {})
    has_routing = design_name in session.get("routing", {})
    stages_done: list[str] = []
    if has_design:
        stages_done.append("parse/synthesize")
    if has_erc:
        stages_done.append("validate")
    if has_positions:
        stages_done.append("place")
    if has_routing:
        stages_done.append("route")
    return {
        "design": design_name,
        "exists": has_design,
        "stages_completed": stages_done,
        "erc_done": has_erc,
        "placement_done": has_positions,
        "routing_done": has_routing,
    }


# ---------------------------------------------------------------------------
# Tool 24 — patch_suggest
# ---------------------------------------------------------------------------


def tool_patch_suggest(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Suggest auto-patches for fixable ERC violations."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    erc_result = session.get("erc_results", {}).get(design_name)
    if erc_result is None:
        raise ValueError(f"No ERC result for '{design_name}'")
    patches = suggest_patches(design, erc_result)
    return {"design": design_name, "patches": patches}


# ---------------------------------------------------------------------------
# Tool 25 — board_update
# ---------------------------------------------------------------------------


def tool_board_update(
    design_name: str,
    width_mm: float | None = None,
    height_mm: float | None = None,
    layers: int | None = None,
    session_id: str = "default",
) -> dict[str, Any]:  # noqa: E501
    """Update board configuration parameters."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    if width_mm is not None:
        design.board.width_mm = width_mm
    if height_mm is not None:
        design.board.height_mm = height_mm
    if layers is not None:
        design.board.layers = layers
    return {
        "design": design_name,
        "width_mm": design.board.width_mm,
        "height_mm": design.board.height_mm,
        "layers": design.board.layers,
    }


# ---------------------------------------------------------------------------
# Tool 26 — component_add
# ---------------------------------------------------------------------------


def tool_component_add(
    design_name: str,
    component_id: str,
    ref: str,
    type_name: str,
    value: str | None = None,
    footprint: str = "",
    session_id: str = "default",
) -> dict[str, Any]:  # noqa: E501
    """Add a new component to a design."""
    import uuid

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    comp = Component(
        id=component_id or str(uuid.uuid4())[:8],
        ref=ref,
        type=type_name,
        value=value,
        footprint=footprint,
    )
    design.components[comp.id] = comp
    return {
        "design": design_name,
        "component_id": comp.id,
        "ref": ref,
        "type": type_name,
    }


# ---------------------------------------------------------------------------
# Tool 27 — component_remove
# ---------------------------------------------------------------------------


def tool_component_remove(design_name: str, component_id: str, session_id: str = "default") -> dict[str, Any]:
    """Remove a component from a design."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    if component_id not in design.components:
        raise ValueError(f"Component '{component_id}' not in design")
    ref = design.components[component_id].ref
    del design.components[component_id]
    # Remove orphaned net nodes
    nets_to_remove: list[str] = []
    for net_id, net in design.nets.items():
        net.nodes = [n for n in net.nodes if n.component_ref != ref]
        if not net.nodes:
            nets_to_remove.append(net_id)
    for net_id in nets_to_remove:
        del design.nets[net_id]
    return {
        "design": design_name,
        "removed_component": component_id,
        "ref": ref,
        "removed_orphan_nets": nets_to_remove,
    }


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# New Phase 1 tools — Gerber, DRC, board, footprint
# ---------------------------------------------------------------------------


def tool_export_gerber(
    design_name: str,
    output_dir: str | None = None,
    approval_id: str | None = None,
    session_id: str = "default",
) -> dict[str, Any]:
    """Generate Gerber RS-274X files for a design."""
    from zaptrace.export.gerber import generate_gerber

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    out_path = _validate_path(output_dir) if output_dir else None
    release_gate = _require_release_gate(session, design_name, approval_id)
    result = generate_gerber(design, output_dir=out_path) if out_path else generate_gerber(design)
    return {
        "design": design_name,
        "layers": list(result.keys()),
        "files": {k: str(v) for k, v in result.items()} if output_dir else result,
        "release_gate": release_gate,
    }


def tool_export_excellon(
    design_name: str,
    output_dir: str | None = None,
    approval_id: str | None = None,
    session_id: str = "default",
) -> dict[str, Any]:
    """Generate Excellon drill files for a design."""
    from zaptrace.export.excellon import generate_composite_drill, generate_excellon

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    out = _validate_path(output_dir) if output_dir else None
    release_gate = _require_release_gate(session, design_name, approval_id)
    if out:
        files = generate_excellon(design, output_dir=out)
        return {
            "design": design_name,
            "files": {k: str(v) for k, v in files.items()},
            "release_gate": release_gate,
        }
    drill = generate_composite_drill(design)
    return {"design": design_name, "drill": drill, "release_gate": release_gate}


# ---------------------------------------------------------------------------
# DRC tools
# ---------------------------------------------------------------------------


def _get_drc_engine(fab_profile: str | None = None) -> Any:
    from zaptrace.ee.drc.engine import DRCEngine

    if fab_profile:
        from zaptrace.fab.profile import load_profile

        return DRCEngine(fab_profile=load_profile(fab_profile))
    return DRCEngine()


def tool_drc_run(design_name: str, fab_profile: str | None = None, session_id: str = "default") -> dict[str, Any]:
    """Run DRC on a design, optionally against a manufacturer fab profile.

    When ``fab_profile`` is a built-in profile name (e.g. ``"jlcpcb-2layer"``),
    DRC also reports that fab's profile-specific violations (min trace/space/
    drill/annular ring, via and board limits).
    """
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    engine = _get_drc_engine(fab_profile)
    result = engine.run(design)
    session.setdefault("drc_results", {})[design_name] = result
    validation = _record_validation_status(session, design_name)
    return {
        "design": design_name,
        "fab_profile": fab_profile,
        "passed": result.passed,
        "validation_status": validation,
        "total_violations": result.total_violations,
        "violations": [
            {"rule_id": v.rule_id, "severity": v.severity.value, "message": v.message} for v in result.violations
        ],
    }


def tool_drc_get_result(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Get the latest DRC result for a design."""
    session = _get_session(session_id)
    result = session.get("drc_results", {}).get(design_name)
    if result is None:
        return {"design": design_name, "result": None, "message": "No DRC result found. Run drc_run first."}
    return {
        "design": design_name,
        "passed": result.passed,
        "total_violations": result.total_violations,
        "violations": [
            {"rule_id": v.rule_id, "severity": v.severity.value, "message": v.message} for v in result.violations
        ],
    }


def tool_drc_list_rules() -> dict[str, Any]:
    """List all DRC rules with descriptions."""
    from zaptrace.ee.drc import list_drc_rules

    rules = list_drc_rules()
    return {"rules": rules, "count": len(rules)}


# ---------------------------------------------------------------------------
# Design analysis tools (mechanical / security / testability)
# ---------------------------------------------------------------------------


def _require_design(design_name: str, session_id: str) -> Any:
    design = _get_session(session_id).get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    return design


def tool_mechanical_review(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Review mounting holes vs board size and edges (mechanical / enclosure)."""
    from zaptrace.analysis.mechanical import mechanical_review

    design = _require_design(design_name, session_id)
    findings = mechanical_review(design)
    return {"design": design_name, "finding_count": len(findings), "findings": [f.to_dict() for f in findings]}


def tool_security_review(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Review hardware-security exposure (debug access, secure element, etc.)."""
    from zaptrace.analysis.security_review import security_review

    design = _require_design(design_name, session_id)
    findings = security_review(design)
    return {"design": design_name, "finding_count": len(findings), "findings": [f.to_dict() for f in findings]}


def tool_testability_report(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Assess test-point coverage, debug/reset access, and a bring-up checklist."""
    from zaptrace.analysis.dft import analyze_testability, bringup_checklist

    design = _require_design(design_name, session_id)
    report = analyze_testability(design)
    return {"design": design_name, "report": report.to_dict(), "bringup_checklist": bringup_checklist(design)}


def tool_electrical_analysis(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Heuristic SI/PI/thermal pre-check (impedance, length-match, PDN, thermal).

    A pre-check, not signoff — the report carries its own assumptions and
    limitations.
    """
    from zaptrace.analysis.reports import generate_electrical_analysis_report

    design = _require_design(design_name, session_id)
    report = generate_electrical_analysis_report(design)
    return {"design": design_name, "report": report.model_dump()}


def tool_requirements_parse(intent: str) -> dict[str, Any]:
    """Extract requirements, the constraints they imply, a coverage matrix, and assumptions."""
    from zaptrace.synthesis.requirements import (
        classify_risk,
        freeze_requirements,
        parse_requirements,
        requirements_assumptions,
        requirements_conflicts,
        requirements_coverage,
        requirements_to_constraints,
        review_assumptions,
    )

    requirements = parse_requirements(intent)
    return {
        "intent": intent,
        "requirements": requirements.to_dict(),
        "constraints": requirements_to_constraints(requirements).model_dump(),
        "coverage": requirements_coverage(requirements),
        "assumptions": requirements_assumptions(requirements),
        "conflicts": requirements_conflicts(requirements),
        "freeze": freeze_requirements(requirements),
        "assumption_review": review_assumptions(requirements),
        "risk": classify_risk(requirements),
    }


def tool_requirements_review(intent: str, approvals: dict[str, str] | None = None) -> dict[str, Any]:
    """Approve a design's unspecified assumptions and gate on any still pending.

    ``approvals`` maps an assumption ``field`` to the reviewer's decision for it;
    the gate is ``approved`` only when no assumption remains pending. Bound to the
    requirements freeze hash, so a later requirement change re-opens the gate.
    """
    from zaptrace.synthesis.requirements import parse_requirements, review_assumptions

    requirements = parse_requirements(intent)
    return {
        "intent": intent,
        "review": review_assumptions(requirements, approvals),
    }


def tool_power_tree_plan(intent: str) -> dict[str, Any]:
    """Plan a justified power tree (sources, charger, power-path, per-rail regulators) from an intent."""
    from zaptrace.synthesis.power_tree import plan_power_tree
    from zaptrace.synthesis.requirements import parse_requirements

    requirements = parse_requirements(intent)
    return {"intent": intent, "power_tree": plan_power_tree(requirements)}


def tool_synthesize_power_tree(intent: str, session_id: str = "default") -> dict[str, Any]:
    """Emit a real netlist (components + nets) for an intent's power tree and store it in the session."""
    from zaptrace.synthesis.power_tree import build_power_tree_design, plan_power_tree
    from zaptrace.synthesis.requirements import parse_requirements

    requirements = parse_requirements(intent)
    plan = plan_power_tree(requirements)
    design = build_power_tree_design(requirements)
    session = _get_session(session_id)
    session["designs"][design.meta.name] = design
    unrealized = [s for s in plan["stages"] if s["stage"] == "regulator" and s["topology"] == "boost"]
    return {
        "intent": intent,
        "design_name": design.meta.name,
        "component_count": len(design.components),
        "net_count": len(design.nets),
        "blocks": [b.name for b in design.blocks],
        "unrealized_stages": unrealized,
        "method": "rule_based_power_tree_synthesis",
    }


def tool_synthesize_and_check(intent: str, session_id: str = "default") -> dict[str, Any]:
    """Synthesize an intent's power tree into a netlist and run ERC on it in one step.

    Closes the intent -> netlist -> verification loop: builds the power-tree
    `Design`, stores it in the session, then validates it with the full ERC rule
    set so the agent can immediately see what its own synthesis produced.
    """
    synth = tool_synthesize_power_tree(intent, session_id=session_id)
    session = _get_session(session_id)
    design = session["designs"][synth["design_name"]]
    result = ERCRunner().run(design)
    session["erc_results"] = {**session.get("erc_results", {}), synth["design_name"]: result}
    return {
        "intent": intent,
        "design_name": synth["design_name"],
        "component_count": synth["component_count"],
        "net_count": synth["net_count"],
        "blocks": synth["blocks"],
        "unrealized_stages": synth["unrealized_stages"],
        "erc": {
            "passed": result.passed,
            "total_errors": result.total_errors,
            "total_warnings": result.total_warnings,
            "violations": [
                {"rule_id": v.rule_id, "severity": v.severity.value, "message": v.message} for v in result.violations
            ],
        },
    }


def tool_board_plan(intent: str) -> dict[str, Any]:
    """Plan a justified board block graph (power + interface support) from an intent."""
    from zaptrace.synthesis.architecture import plan_architecture
    from zaptrace.synthesis.requirements import parse_requirements

    requirements = parse_requirements(intent)
    return {"intent": intent, "architecture": plan_architecture(requirements).to_dict()}


def tool_synthesize_board(intent: str, session_id: str = "default") -> dict[str, Any]:
    """Emit a real netlist (power + interface blocks) for an intent's board and store it.

    Generalizes power-tree synthesis to the whole board via block composition:
    each regulator provides a rail, each interface support block requires one,
    and unrealized/unmet items are reported instead of silently dropped.
    """
    from zaptrace.synthesis.architecture import build_architecture_design
    from zaptrace.synthesis.requirements import parse_requirements

    requirements = parse_requirements(intent)
    design, plan, log = build_architecture_design(requirements)
    session = _get_session(session_id)
    session["designs"][design.meta.name] = design
    return {
        "intent": intent,
        "design_name": design.meta.name,
        "component_count": len(design.components),
        "net_count": len(design.nets),
        "blocks": [b.name for b in design.blocks],
        "unrealized_blocks": [b.block_id for b in plan.unrealized_blocks],
        "unmet_requirements": [{"block_id": u.block_id, "token": u.token} for u in plan.unmet],
        "decisions": log.to_dicts(),
        "method": "block_composition_synthesis",
    }


def tool_synthesize_board_and_check(intent: str, session_id: str = "default") -> dict[str, Any]:
    """Synthesize an intent's full board into a netlist and run ERC on it in one step.

    Closes the intent -> block graph -> netlist -> verification loop for the whole
    board, not just the power tree.
    """
    synth = tool_synthesize_board(intent, session_id=session_id)
    session = _get_session(session_id)
    design = session["designs"][synth["design_name"]]
    result = ERCRunner().run(design)
    session["erc_results"] = {**session.get("erc_results", {}), synth["design_name"]: result}
    return {
        "intent": intent,
        "design_name": synth["design_name"],
        "component_count": synth["component_count"],
        "net_count": synth["net_count"],
        "blocks": synth["blocks"],
        "unrealized_blocks": synth["unrealized_blocks"],
        "unmet_requirements": synth["unmet_requirements"],
        "erc": {
            "passed": result.passed,
            "total_errors": result.total_errors,
            "total_warnings": result.total_warnings,
            "violations": [
                {"rule_id": v.rule_id, "severity": v.severity.value, "message": v.message} for v in result.violations
            ],
        },
    }


def tool_synthesize_board_repair(intent: str, session_id: str = "default") -> dict[str, Any]:
    """Synthesize a board, run the convergent ERC -> patch -> re-verify loop, and store it.

    Closes the full self-correction loop: build the block-composition netlist, then
    repair every auto-fixable ERC violation (e.g. missing footprints) until a fixed
    point, reporting what was patched and what still needs a human (e.g. single-pin
    nets that require a real connector).
    """
    from zaptrace.synthesis.repair import synthesize_and_repair

    out = synthesize_and_repair(intent)
    design = out["design"]
    plan = out["plan"]
    repair = out["repair"]
    footprints = out["footprints"]
    session = _get_session(session_id)
    session["designs"][design.meta.name] = design
    return {
        "intent": intent,
        "design_name": design.meta.name,
        "component_count": len(design.components),
        "net_count": len(design.nets),
        "converged": repair.converged,
        "fully_clean": repair.fully_clean,
        "patch_count": len(repair.patches),
        "patches": [p.to_dict() for p in repair.patches],
        "remaining": repair.remaining,
        "unrealized_blocks": [b.block_id for b in plan.unrealized_blocks],
        "footprints": footprints.to_dict(),
        "method": "block_composition_synthesis_with_self_repair",
    }


def tool_resolve_footprints(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Attach real IPC-7351 pad geometry to a stored design's components.

    The manufacturing exporters need `footprint_def` geometry, not just a name.
    Components whose package has no generator yet (e.g. an MCU module) are
    reported as unresolved — a visible fabrication blocker, never faked.
    """
    from zaptrace.synthesis.footprint_resolver import resolve_footprints

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    resolution = resolve_footprints(design)
    return {"design": design_name, **resolution.to_dict()}


def tool_dc_bias_check(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Check power-rail bias on a stored design (always available, no ngspice).

    Assigns each power net its nominal DC voltage and flags any rail that loads
    depend on but no regulator drives (a floating-rail bug ERC cannot catch).
    """
    from zaptrace.analysis.dc_bias import resolve_dc_bias

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    return {"design": design_name, **resolve_dc_bias(design).to_dict()}


def tool_simulation_gate(design_name: str, strict: bool = False, session_id: str = "default") -> dict[str, Any]:
    """Run the DC operating-point simulation gate on a stored design.

    Returns a blocking verdict. Rail references are derived from the design's
    power-rail net names. When ngspice is unavailable the gate is `skipped`
    (recorded as evidence, never a silent pass); with `strict=True` a skip blocks.
    """
    from zaptrace.analysis.sim_gate import run_simulation_gate

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    result = run_simulation_gate(design, strict=strict)
    return {"design": design_name, **result.to_dict()}


def tool_synthesis_benchmark() -> dict[str, Any]:
    """Synthesize a fixed corpus of board types and report aggregate completeness.

    Measures the engine, not one board: mean score, per-dimension pass rates, the
    weakest dimension, and the worst case — a deterministic, regression-catching
    snapshot of how finished synthesis is across representative intents.
    """
    from zaptrace.synthesis.benchmark import run_benchmark

    return run_benchmark().to_dict()


def tool_synthesize_board_score(intent: str, session_id: str = "default") -> dict[str, Any]:
    """Synthesize a board end to end and score its completeness (0-100).

    Runs the full flow (block composition + functional core + sensors + repair +
    footprint geometry), stores the design, and returns a weighted completeness
    score across functional-core, composition, electrical, and manufacturability
    dimensions. The score tracks how finished the *automated* steps are — it is
    not a correctness or safety claim; human review still applies.
    """
    from zaptrace.analysis.dc_bias import resolve_dc_bias
    from zaptrace.synthesis.repair import synthesize_and_repair
    from zaptrace.synthesis.scorecard import score_board

    out = synthesize_and_repair(intent)
    design = out["design"]
    session = _get_session(session_id)
    session["designs"][design.meta.name] = design
    card = score_board(design, out["plan"], out["repair"], out["footprints"], resolve_dc_bias(design))
    return {
        "intent": intent,
        "design_name": design.meta.name,
        "component_count": len(design.components),
        **card.to_dict(),
    }


def tool_synthesize_board_manufacture(intent: str, output_dir: str, session_id: str = "default") -> dict[str, Any]:
    """Synthesize a board from intent and emit a full manufacturing bundle + evidence.

    Runs the whole chain — block composition, functional core, peripherals, repair,
    footprint geometry, place, route, and manufacturing export (Gerber, drill, BOM,
    pick-and-place, ZIP) — then returns the completeness score, DC bias, the artifact
    list, and an explicit human-review checklist of what is NOT finished. The bundle
    is never fabrication-ready; the checklist is the honest hand-off.
    """
    from zaptrace.synthesis.fab import synthesize_to_manufacturing

    _get_session(session_id)  # validate/scope the session
    return synthesize_to_manufacturing(intent, output_dir).to_dict()


def tool_compliance_checklist(intent: str) -> dict[str, Any]:
    """Produce a product-class compliance pre-check checklist for a design intent.

    Evidence-ready, not certified — items flag where a manual lab test is
    required.
    """
    from zaptrace.analysis.compliance import compliance_checklist
    from zaptrace.synthesis.requirements import parse_requirements

    requirements = parse_requirements(intent)
    items = compliance_checklist(requirements)
    return {"intent": intent, "item_count": len(items), "items": [i.to_dict() for i in items]}


# ---------------------------------------------------------------------------
# Board / net classification tools
# ---------------------------------------------------------------------------


def tool_board_classify_nets(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Classify all nets in a design using EE knowledge."""
    from zaptrace.ee.classifier import classify_design, summarize_classification

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    classify_design(design)
    summary = summarize_classification(design)
    return {"design": design_name, "classification": summary}


def tool_board_export(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Export the board definition for a design as a JSON description."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    board = design.board
    return {
        "design": design_name,
        "board": {
            "width_mm": board.width_mm,
            "height_mm": board.height_mm,
            "layers": board.layers,
            "edge_clearance_mm": board.edge_clearance_mm,
            "routing_grid_mm": board.routing_grid_mm,
        },
        "component_count": len(design.components),
        "net_count": len(design.nets),
    }


def tool_board_summarize_nets(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Get a summary of all nets and their classifications."""
    from zaptrace.ee.classifier import get_net_class, summarize_classification

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    net_list = []
    for net_id, net in design.nets.items():
        nc = get_net_class(design, net_id)
        net_list.append({"net_id": net_id, "name": net.name, "class": nc.value, "nodes": len(net.nodes)})
    summary = summarize_classification(design)
    return {"design": design_name, "nets": net_list, "classification_summary": summary}


# ---------------------------------------------------------------------------
# Smart routing tool
# ---------------------------------------------------------------------------


def tool_design_route_smart(design_name: str, layer: str = "F.Cu", session_id: str = "default") -> dict[str, Any]:
    """Route all nets with net-class-aware trace widths."""
    from zaptrace.algo.router import route_design_smart
    from zaptrace.ee.knowledge import KnowledgeBase

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    positions = session.get("positions", {}).get(design_name)
    if not positions:
        raise ValueError(f"No placement positions found for '{design_name}'. Run place_components first.")
    kb = KnowledgeBase()
    routing_result, route_result, _sc = route_design_smart(design, positions, kb=kb, layer=layer)
    session.setdefault("routing_results", {})[design_name] = route_result
    return {
        "design": design_name,
        "routed_nets": routing_result.routed_nets,
        "total_nets": routing_result.total_nets,
        "unrouted_nets": routing_result.unrouted_nets,
        "coverage_pct": routing_result.coverage_pct,
        "total_trace_length_mm": route_result.total_trace_length_mm,
        "trace_count": len(route_result.traces),
    }


def tool_design_classify_nets(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Classify a single net or all nets in a design."""
    from zaptrace.ee.classifier import classify_design

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    classify_design(design)
    net_classes = {}
    for nid, nc in (design.net_classes or {}).items():
        net = design.nets.get(nid)
        net_classes[nid] = {"name": net.name if net else "?", "class": nc.value}
    return {"design": design_name, "nets_classified": len(net_classes), "classifications": net_classes}


# ---------------------------------------------------------------------------
# Footprint search tools
# ---------------------------------------------------------------------------


def tool_footprint_search(query: str, max_results: int = 10) -> dict[str, Any]:
    """Search for footprints in the library by keyword."""
    library = _get_library()
    results = library.search(query, max_results=max_results)
    footprints = []
    for r in results:
        fp = r.footprint or r.package
        footprints.append(
            {
                "id": r.id,
                "name": r.name,
                "type": r.category,
                "footprint": fp,
                "description": r.description,
            }
        )
    return {"query": query, "count": len(footprints), "footprints": footprints}


def tool_footprint_get(component_id: str) -> dict[str, Any]:
    """Get footprint details for a library component."""
    library = _get_library()
    try:
        comp = library.get(component_id)
    except Exception as e:
        return {"component_id": component_id, "error": str(e)}
    return {
        "component_id": component_id,
        "footprint": comp.footprint,
        "package": comp.package,
        "manufacturer": comp.manufacturer,
        "datasheet": comp.datasheet,
    }


# ---------------------------------------------------------------------------
# Phase 2 tool implementations
# ---------------------------------------------------------------------------


def tool_schematic_render(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Render a design as an SVG schematic using the SchematicEngine."""
    from zaptrace.ee.schematic import SchematicEngine

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    engine = SchematicEngine()
    svg = engine.render(design)
    return {"svg": svg, "design": design_name}


def tool_footprint_generate(package: str, layer: str = "top") -> dict[str, Any]:
    """Generate a parametric footprint for a given package name."""
    from zaptrace.core.models import LayerSet
    from zaptrace.ee.footprints import generate_footprint

    layer_enum = LayerSet.BOTTOM if layer.lower() == "bottom" else LayerSet.TOP
    fp = generate_footprint(package, layer=layer_enum)
    if fp is None:
        return {"package": package, "error": f"Unknown package: {package}"}
    return {
        "package": package,
        "pads": [p.model_dump() for p in fp.pads],
        "outline_commands": [c.model_dump() for c in fp.outline],
        "courtyard_w": fp.courtyard[0],
        "courtyard_h": fp.courtyard[1],
        "description": fp.description,
    }


def tool_footprint_list_packages() -> dict[str, Any]:
    """List all supported package names for footprint generation."""
    from zaptrace.ee.footprints import list_supported_packages

    return {"packages": list_supported_packages(), "count": len(list_supported_packages())}


def tool_export_manufacturing(
    design_name: str,
    output_dir: str,
    approval_id: str | None = None,
    session_id: str = "default",
) -> dict[str, Any]:
    """Generate a complete manufacturing package (Gerber + drill + BOM + PnP + ZIP)."""
    from zaptrace.export.manufacturing import generate_manufacturing_bundle

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    out_dir = _validate_path(output_dir)
    release_gate = _require_release_gate(session, design_name, approval_id)
    result = generate_manufacturing_bundle(design, str(out_dir), prefix=design_name)
    return {
        "design": design_name,
        "output_dir": output_dir,
        "release_gate": release_gate,
        "gerber_layers": list(result.get("gerber_layers", {}).keys()),
        "bom": result.get("bom", ""),
        "pick_and_place": result.get("pick_and_place", ""),
        "manifest": result.get("manifest", ""),
        "zip": result.get("zip", ""),
    }


def tool_export_pick_and_place(
    design_name: str,
    approval_id: str | None = None,
    session_id: str = "default",
) -> dict[str, Any]:
    """Generate a pick-and-place (centroid) CSV for a design."""
    from zaptrace.export.manufacturing import generate_pick_and_place

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    release_gate = _require_release_gate(session, design_name, approval_id)
    csv = generate_pick_and_place(design)
    return {
        "csv": csv,
        "design": design_name,
        "count": csv.count("\n") - 1,
        "release_gate": release_gate,
    }


# ---------------------------------------------------------------------------
# Transaction safety — design snapshots
# ---------------------------------------------------------------------------


def tool_design_snapshot(
    design_name: str,
    label: str | None = None,
    session_id: str = "default",
) -> dict[str, Any]:
    """Capture a point-in-time snapshot of a design for later rollback.

    Snapshots are stored per-design in the session.  Use a unique *label*
    to distinguish multiple snapshots; auto-generates a timestamp-based
    label if omitted.
    """
    import copy
    import time

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")

    snapshot_label = label or f"snap-{int(time.time() * 1000)}"
    session.setdefault("snapshots", {}).setdefault(design_name, {})[snapshot_label] = copy.deepcopy(design)

    # Also snapshot ancillary state
    ancillary = {
        "positions": copy.deepcopy(session.get("positions", {}).get(design_name)),
        "erc_results": copy.deepcopy(session.get("erc_results", {}).get(design_name)),
        "drc_results": copy.deepcopy(session.get("drc_results", {}).get(design_name)),
        "routing_results": copy.deepcopy(session.get("routing_results", {}).get(design_name)),
    }
    session.setdefault("snapshots_ancillary", {}).setdefault(design_name, {})[snapshot_label] = ancillary

    return {
        "design": design_name,
        "snapshot": snapshot_label,
        "component_count": len(design.components),
        "net_count": len(design.nets),
    }


def tool_design_rollback(
    design_name: str,
    label: str,
    session_id: str = "default",
) -> dict[str, Any]:
    """Restore a design (and ancillary state) from a named snapshot.

    Raises ``ValueError`` if the snapshot does not exist.
    """
    session = _get_session(session_id)
    snapshots = session.get("snapshots", {}).get(design_name, {})
    if label not in snapshots:
        available = list(snapshots.keys())
        raise ValueError(f"Snapshot '{label}' not found for design '{design_name}'. Available: {available}")

    # Restore design
    session["designs"][design_name] = snapshots[label]

    # Restore ancillary state
    ancillary = session.get("snapshots_ancillary", {}).get(design_name, {}).get(label, {})
    for key, value in ancillary.items():
        if value is not None:
            session.setdefault(key, {})[design_name] = value
        else:
            session.get(key, {}).pop(design_name, None)

    return {
        "design": design_name,
        "restored_from": label,
        "component_count": len(snapshots[label].components),
        "net_count": len(snapshots[label].nets),
    }


def tool_design_list_snapshots(
    design_name: str | None = None,
    session_id: str = "default",
) -> dict[str, Any]:
    """List available snapshots for a design (or all designs)."""
    session = _get_session(session_id)
    all_snaps = session.get("snapshots", {})

    if design_name:
        snaps = all_snaps.get(design_name, {})
        return {
            "design": design_name,
            "snapshots": [
                {
                    "label": label,
                    "component_count": len(d.components),
                    "net_count": len(d.nets),
                }
                for label, d in snaps.items()
            ],
            "count": len(snaps),
        }

    result = {}
    for dname, snaps in all_snaps.items():
        result[dname] = [
            {
                "label": label,
                "component_count": len(d.components),
                "net_count": len(d.nets),
            }
            for label, d in snaps.items()
        ]
    return {"snapshots_by_design": result, "total_snapshots": sum(len(v) for v in all_snaps.values())}


def tool_design_commit(
    design_name: str,
    label: str | None = None,
    session_id: str = "default",
) -> dict[str, Any]:
    """Confirm design changes by removing old snapshots.

    If *label* is provided, only that snapshot is removed (confirming the
    state at that point).  If *label* is None, all snapshots for the
    design are cleared.
    """
    session = _get_session(session_id)
    snaps = session.get("snapshots", {}).get(design_name, {})
    anc = session.get("snapshots_ancillary", {}).get(design_name, {})

    if label:
        removed = snaps.pop(label, None)
        anc.pop(label, None)
        if removed is None:
            available = list(snaps.keys())
            raise ValueError(f"Snapshot '{label}' not found for '{design_name}'. Available: {available}")
    else:
        removed = bool(snaps)
        session["snapshots"][design_name] = {}
        session["snapshots_ancillary"][design_name] = {}

    return {
        "design": design_name,
        "removed_snapshots": 1 if label else len(snaps) if not label and removed else 0,
        "remaining_snapshots": len(session.get("snapshots", {}).get(design_name, {})),
    }


# ---------------------------------------------------------------------------
# Transaction runtime — preview, validate, commit, rollback
# ---------------------------------------------------------------------------


def _apply_transaction_operation(design: Any, operation: str, params: dict[str, Any]) -> None:
    """Apply a supported transaction operation to a candidate design copy."""
    if operation == "board_update":
        if params.get("width_mm") is not None:
            design.board.width_mm = float(params["width_mm"])
        if params.get("height_mm") is not None:
            design.board.height_mm = float(params["height_mm"])
        if params.get("layers") is not None:
            design.board.layers = int(params["layers"])
        return

    if operation == "component_add":
        import uuid

        component_id = str(params.get("component_id") or str(uuid.uuid4())[:8])
        comp = Component(
            id=component_id,
            ref=str(params["ref"]),
            type=str(params["type_name"]),
            value=params.get("value"),
            footprint=str(params.get("footprint") or ""),
        )
        design.components[comp.id] = comp
        return

    if operation == "component_remove":
        component_id = str(params["component_id"])
        if component_id not in design.components:
            raise ValueError(f"Component '{component_id}' not in design")
        ref = design.components[component_id].ref
        del design.components[component_id]
        nets_to_remove: list[str] = []
        for net_id, net in design.nets.items():
            net.nodes = [n for n in net.nodes if n.component_ref != ref]
            if not net.nodes:
                nets_to_remove.append(net_id)
        for net_id in nets_to_remove:
            del design.nets[net_id]
        return

    raise ValueError(f"Unsupported transaction operation: {operation}")


def _semantic_diff_records(entries: list[Any]) -> list[dict[str, Any]]:
    """Return JSON-safe semantic diff records."""
    return [
        {
            "type": entry.type.value if hasattr(entry.type, "value") else str(entry.type),
            "ref": entry.ref,
            "detail": entry.detail,
            "old_value": entry.old_value,
            "new_value": entry.new_value,
        }
        for entry in entries
    ]


def _transaction_public_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a serializable transaction record without candidate object internals."""
    hidden = {"candidate_design"}
    return {k: v for k, v in record.items() if k not in hidden}


def tool_design_transaction_preview(
    design_name: str,
    operation: str,
    params: dict[str, Any],
    reason: str = "",
    session_id: str = "default",
) -> dict[str, Any]:
    """Preview a design mutation as an isolated transaction without committing it."""
    import time
    import uuid

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")

    candidate = copy.deepcopy(design)
    _apply_transaction_operation(candidate, operation, params)
    entries = diff_designs(design, candidate)
    tx_id = f"tx-{int(time.time() * 1000)}-{str(uuid.uuid4())[:8]}"
    record = {
        "transaction_id": tx_id,
        "design_name": design_name,
        "operation": operation,
        "params": params,
        "state": "previewed",
        "reason": reason,
        "parent_state_hash": design_state_hash(design),
        "preview_state_hash": design_state_hash(candidate),
        "changed_entities": [entry.ref for entry in entries],
        "semantic_diff": _semantic_diff_records(entries),
        "validation": {"status": "not_run", "required_before_commit": True},
        "candidate_design": candidate,
    }
    session.setdefault("transactions", {})[tx_id] = record
    return _transaction_public_record(record)


def tool_design_transaction_validate(transaction_id: str, session_id: str = "default") -> dict[str, Any]:
    """Run validation against a transaction candidate without mutating primary state."""
    session = _get_session(session_id)
    record = session.get("transactions", {}).get(transaction_id)
    if record is None:
        raise ValueError(f"Transaction '{transaction_id}' not found")
    if record["state"] not in {"previewed", "validated"}:
        raise ValueError(f"Transaction '{transaction_id}' cannot be validated from state {record['state']}")

    candidate = record["candidate_design"]
    runner = ERCRunner()
    result = runner.run(candidate)
    validation = {
        "status": "passed" if result.passed else "failed",
        "erc_errors": result.total_errors,
        "erc_warnings": result.total_warnings,
        "erc_info": result.total_info,
    }
    record["validation"] = validation
    record["state"] = "validated" if result.passed else "rejected"
    return _transaction_public_record(record)


def tool_design_transaction_commit(
    transaction_id: str,
    approval_id: str,
    session_id: str = "default",
) -> dict[str, Any]:
    """Commit a validated transaction after explicit approval."""
    if not approval_id or not approval_id.strip():
        raise ValueError("approval_id is required to commit a transaction")

    session = _get_session(session_id)
    record = session.get("transactions", {}).get(transaction_id)
    if record is None:
        raise ValueError(f"Transaction '{transaction_id}' not found")
    if record["state"] != "validated":
        raise ValueError(f"Transaction '{transaction_id}' must be validated before commit")
    if record.get("validation", {}).get("status") != "passed":
        raise ValueError(f"Transaction '{transaction_id}' validation did not pass")

    design_name = record["design_name"]
    previous = session.get("designs", {}).get(design_name)
    candidate = record["candidate_design"]
    if previous is None:
        raise ValueError(f"Design '{design_name}' not found")
    if design_state_hash(previous) != record["parent_state_hash"]:
        record["state"] = "rejected"
        raise ValueError("Primary design state changed since preview; re-preview is required")

    session["designs"][design_name] = copy.deepcopy(candidate)
    record["state"] = "committed"
    record["approval_id"] = approval_id
    record["committed_state_hash"] = design_state_hash(candidate)
    session.setdefault("transaction_history", []).append(_transaction_public_record(record))
    return _transaction_public_record(record)


def tool_design_transaction_rollback(transaction_id: str, session_id: str = "default") -> dict[str, Any]:
    """Reject or roll back a preview transaction without changing primary state."""
    session = _get_session(session_id)
    record = session.get("transactions", {}).get(transaction_id)
    if record is None:
        raise ValueError(f"Transaction '{transaction_id}' not found")
    if record["state"] == "committed":
        raise ValueError("Committed transactions cannot be rolled back by preview rollback")
    record["state"] = "rolled_back"
    session.setdefault("transaction_history", []).append(_transaction_public_record(record))
    return _transaction_public_record(record)


def tool_design_transaction_list(session_id: str = "default") -> dict[str, Any]:
    """List transactions for a session."""
    session = _get_session(session_id)
    transactions = [_transaction_public_record(r) for r in session.get("transactions", {}).values()]
    return {"session_id": session_id, "transactions": transactions, "count": len(transactions)}


# ---------------------------------------------------------------------------
# Proof Pack tools
# ---------------------------------------------------------------------------


def tool_proof_run(path: str) -> dict[str, Any]:
    """Run a Proof Pack from a file or directory path."""
    from zaptrace.proof import run_proof

    p = _validate_path(path, must_exist=True)
    pack = run_proof(str(p))
    return {
        "name": pack.manifest.name,
        "passed": pack.passed,
        "total": len(pack.results),
        "passed_count": sum(1 for r in pack.results if r.passed),
        "failed_count": sum(1 for r in pack.results if not r.passed and r.status != "skip"),
        "skipped_count": sum(1 for r in pack.results if r.status == "skip"),
        "results": [r.to_dict() for r in pack.results],
        "autonomous_signoff": pack.autonomous_signoff.to_evidence_record(),
        "summary": pack.summary,
    }


def tool_proof_run_design(
    design_name: str,
    checks: list[dict] | None = None,
    session_id: str = "default",
) -> dict[str, Any]:
    """Run proof checks directly against a design in the current session.

    If checks is None, only validates that the design loads (structural check).
    """
    from zaptrace.proof import CheckDefinition, ProofRunner

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")

    runner = ProofRunner(design)
    check_defs = []
    if checks:
        for c in checks:
            check_defs.append(CheckDefinition(**c))
    else:
        # Default: structural validation
        check_defs = [
            CheckDefinition(name="design_exists", type="footprint_exists", description="Verify design loads"),
            CheckDefinition(name="all_routed", type="routed", description="All nets routed"),
            CheckDefinition(
                name="footprints_present",
                type="footprint_exists",
                description="All components have footprints",
            ),
        ]

    results = runner.run_checks(check_defs)
    passed = all(r.passed for r in results)
    return {
        "design": design_name,
        "passed": passed,
        "total": len(results),
        "passed_count": sum(1 for r in results if r.passed),
        "failed_count": sum(1 for r in results if not r.passed and r.status != "skip"),
        "results": [r.to_dict() for r in results],
    }


def tool_proof_list_checks(path: str) -> dict[str, Any]:
    """List all checks defined in a Proof Pack without running them."""

    from zaptrace.proof import ProofPack

    path_obj = _validate_path(path, must_exist=True)
    if path_obj.is_dir():
        path_obj = _validate_path(path_obj / "proof.yaml", must_exist=True)
    pack = ProofPack.load(path_obj)
    return {
        "name": pack.manifest.name,
        "description": pack.manifest.description,
        "version": pack.manifest.version,
        "design_path": pack.manifest.design_path,
        "checks": [
            {
                "name": c.name,
                "type": c.type,
                "severity": c.severity.value,
                "description": c.description,
                "category": c.category.value,
            }
            for c in pack.manifest.checks
        ],
        "constraints": pack.manifest.model.model_dump(),
    }


# ---------------------------------------------------------------------------
# Audit tools
# ---------------------------------------------------------------------------


def tool_audit_list_events(session_id: str = "default", limit: int = 50) -> dict[str, Any]:
    """List recent security/audit events for a session."""
    session = _get_session(session_id)
    events = list(session.get("audit_events", []))
    if limit < 1:
        limit = 1
    return {"session_id": session_id, "count": len(events), "events": events[-limit:]}


# ---------------------------------------------------------------------------
# Calculator + SPICE export tools
# ---------------------------------------------------------------------------


def tool_export_spice(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Export a session design as a SPICE netlist string (foundation for simulation)."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    netlist = export_spice_netlist(design)
    unsupported = sum(1 for line in netlist.splitlines() if line.startswith("* Unsupported:"))
    return {"design": design_name, "netlist": netlist, "unsupported_count": unsupported}


def tool_calc_led_resistor(supply_v: float, forward_v: float, current_ma: float, series: int = 24) -> dict[str, Any]:
    """Size an LED current-limiting resistor (E-series; rounds up so current stays at/under target)."""
    return asdict(led_series_resistor(supply_v, forward_v, current_ma, series=series))


def tool_calc_voltage_divider(input_v: float, output_v: float, r_bottom: float, series: int = 24) -> dict[str, Any]:
    """Choose the top resistor of a divider for a target output voltage (E-series)."""
    return asdict(divider_for_output(input_v, output_v, r_bottom, series=series))


def tool_calc_rc_filter(r_ohms: float, c_farads: float) -> dict[str, Any]:
    """Compute the -3 dB cutoff frequency of a first-order RC filter."""
    return {"cutoff_hz": rc_cutoff_hz(r_ohms, c_farads), "r_ohms": r_ohms, "c_farads": c_farads}


def tool_calc_i2c_pullup(
    supply_v: float,
    bus_capacitance_pf: float,
    bus_speed_hz: int = 100_000,
    series: int = 24,
) -> dict[str, Any]:
    """Compute the I2C pull-up range and a recommended E-series value (NXP UM10204)."""
    return asdict(i2c_pullup(supply_v, bus_capacitance_pf, bus_speed_hz=bus_speed_hz, series=series))


def tool_calc_e_series(value: float, series: int = 24, mode: str = "nearest") -> dict[str, Any]:
    """Snap a value to an E-series preferred value. mode: nearest | ceil | floor."""
    funcs = {"nearest": nearest_e_series, "ceil": e_series_ceil, "floor": e_series_floor}
    if mode not in funcs:
        raise ValueError(f"mode must be one of {sorted(funcs)}")
    return {"value": funcs[mode](value, series), "series": series, "mode": mode}


def tool_calc_usb_c_cc(role: str, advertised_current_a: float | None = None) -> dict[str, Any]:
    """Resolve the USB-C CC-pin termination resistor for a port role (USB-C spec §4.5.1)."""
    return asdict(usb_c_cc_termination(role, advertised_current_a))


def tool_calc_decoupling(power_pins: int, rail_v: float, bulk_uf: float | None = None) -> dict[str, Any]:
    """Plan decoupling caps for a rail: 100 nF per power pin + bulk, with a derated voltage rating."""
    return asdict(decoupling_plan(power_pins, rail_v, bulk_uf=bulk_uf))


def tool_calc_lipo_charge(charge_current_ma: float, series: int = 24) -> dict[str, Any]:
    """Size the PROG resistor for an MCP73831/2 Li-ion/Li-Po charger from a target charge current."""
    return asdict(lipo_charge_resistor(charge_current_ma, series=series))


def tool_calc_buck_lc(
    vin: float,
    vout: float,
    iout: float,
    f_sw_hz: float,
    ripple_ratio: float = 0.3,
    output_ripple_v: float | None = None,
) -> dict[str, Any]:
    """Size a buck converter's inductor + output capacitor (CCM) from Vin/Vout/Iout/Fsw."""
    return asdict(
        buck_inductor_capacitor(vin, vout, iout, f_sw_hz, ripple_ratio=ripple_ratio, output_ripple_v=output_ripple_v)
    )


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "design_parse_file": {
        "name": "design_parse_file",
        "description": "Parse a design YAML file into a Design object",
        "fn": tool_design_parse_file,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "path": {"type": "string", "description": "Path to design YAML file"},
        },
    },
    "design_parse_str": {
        "name": "design_parse_str",
        "description": "Parse a YAML string into a Design object",
        "fn": tool_design_parse_str,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "yaml_content": {"type": "string", "description": "YAML content string"},
        },
    },
    "design_inspect": {
        "name": "design_inspect",
        "description": "Inspect a parsed design and return its full details",
        "fn": tool_design_inspect,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
        },
    },
    "design_list_nets": {
        "name": "design_list_nets",
        "description": "List all nets in a design with their connections",
        "fn": tool_design_list_nets,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
        },
    },
    "synthesize_design": {
        "name": "synthesize_design",
        "description": (
            "Select and load the best-matching pre-built design template for an intent string "
            "(template selection by keyword match, not from-scratch circuit synthesis)"
        ),
        "fn": tool_synthesize_design,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "intent": {"type": "string", "description": "Design intent description"},
        },
    },
    "list_synthesis_templates": {
        "name": "list_synthesis_templates",
        "description": "List available synthesis templates",
        "fn": tool_list_synthesis_templates,
        "params": {},
    },
    "erc_validate": {
        "name": "erc_validate",
        "description": "Run all ERC rules on a design",
        "fn": tool_erc_validate,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
        },
    },
    "erc_get_result": {
        "name": "erc_get_result",
        "description": "Get the latest ERC result summary for a design",
        "fn": tool_erc_get_result,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
        },
    },
    "erc_list_rules": {
        "name": "erc_list_rules",
        "description": "List all registered ERC rules with descriptions",
        "fn": tool_erc_list_rules,
        "params": {},
    },
    "place_components": {
        "name": "place_components",
        "description": "Place all components on the board",
        "fn": tool_place_components,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
        },
    },
    "route_nets": {
        "name": "route_nets",
        "description": "Route all nets using Manhattan MST routing",
        "fn": tool_route_nets,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
        },
    },
    "library_search": {
        "name": "library_search",
        "description": "Search the component library by keyword",
        "fn": tool_library_search,
        "params": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "description": "Max results"},
        },
    },
    "library_get": {
        "name": "library_get",
        "description": "Get full details for a library component",
        "fn": tool_library_get,
        "params": {
            "component_id": {"type": "string", "description": "Component ID"},
        },
    },
    "library_list_categories": {
        "name": "library_list_categories",
        "description": "List all component library categories",
        "fn": tool_library_list_categories,
        "params": {},
    },
    "export_bom_csv": {
        "name": "export_bom_csv",
        "description": "Generate Bill of Materials as CSV",
        "fn": tool_export_bom_csv,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
        },
    },
    "export_bom_json": {
        "name": "export_bom_json",
        "description": "Generate Bill of Materials as JSON",
        "fn": tool_export_bom_json,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
        },
    },
    "export_report": {
        "name": "export_report",
        "description": "Generate a Markdown design report",
        "fn": tool_export_report,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
            "output_path": {"type": "string", "description": "Optional output path"},
        },
    },
    "export_svg": {
        "name": "export_svg",
        "description": "Render a schematic overview as SVG",
        "fn": tool_export_svg,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
            "output_path": {"type": "string", "description": "Optional output path"},
        },
    },
    "export_kicad": {
        "name": "export_kicad",
        "description": "Export design to KiCad-compatible files",
        "fn": tool_export_kicad,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
            "output_dir": {"type": "string", "description": "Output directory"},
            "approval_id": {"type": "string", "description": "External approval or release gate identifier"},
        },
    },
    "kicad_import_project": {
        "name": "kicad_import_project",
        "description": (
            "Import a KiCad project (hierarchical or flat) from the workspace. "
            "Accepts a project directory, .kicad_pro file, or .kicad_sch file. "
            "Returns design identity, sheet hierarchy, net score, and degradation findings. "
            "The imported design is stored in the session under the project name."
        ),
        "fn": tool_kicad_import_project,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "project_path": {
                "type": "string",
                "description": "Path to project directory, .kicad_pro, or .kicad_sch file",
            },
        },
    },
    "design_diff": {
        "name": "design_diff",
        "description": "Diff two designs and report changes",
        "fn": tool_design_diff,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_a_name": {"type": "string", "description": "First design name"},
            "design_b_name": {"type": "string", "description": "Second design name"},
        },
    },
    "pipeline_run": {
        "name": "pipeline_run",
        "description": "Run the full design pipeline from file or intent",
        "fn": tool_pipeline_run,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "source": {"type": "string", "description": "Design file path"},
            "intent": {"type": "string", "description": "Synthesis intent"},
            "output_dir": {"type": "string", "description": "Output directory"},
        },
    },
    "pipeline_run_stage": {
        "name": "pipeline_run_stage",
        "description": "Run a single pipeline stage",
        "fn": tool_pipeline_run_stage,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "stage": {"type": "string", "description": "Stage name"},
            "source": {"type": "string", "description": "Design file path"},
            "intent": {"type": "string", "description": "Synthesis intent"},
            "design_name": {"type": "string", "description": "Design name"},
            "output_dir": {"type": "string", "description": "Output directory"},
        },
    },
    "pipeline_status": {
        "name": "pipeline_status",
        "description": "Get pipeline processing status for a design",
        "fn": tool_pipeline_status,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
        },
    },
    "patch_suggest": {
        "name": "patch_suggest",
        "description": "Suggest auto-patches for fixable ERC violations",
        "fn": tool_patch_suggest,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
        },
    },
    "board_update": {
        "name": "board_update",
        "description": "Update board configuration parameters",
        "fn": tool_board_update,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
            "width_mm": {"type": "number", "description": "Board width in mm"},
            "height_mm": {"type": "number", "description": "Board height in mm"},
            "layers": {"type": "integer", "description": "Number of copper layers"},
        },
    },
    "component_add": {
        "name": "component_add",
        "description": "Add a new component to a design",
        "fn": tool_component_add,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
            "component_id": {"type": "string", "description": "Component ID"},
            "ref": {"type": "string", "description": "Reference designator (e.g. R1, U1)"},
            "type_name": {"type": "string", "description": "Component type"},
            "value": {"type": "string", "description": "Component value"},
            "footprint": {"type": "string", "description": "Footprint name"},
        },
    },
    "component_remove": {
        "name": "component_remove",
        "description": "Remove a component from a design",
        "fn": tool_component_remove,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
            "component_id": {"type": "string", "description": "Component ID to remove"},
        },
    },
    # Phase 1 — Gerber/DRC/Board/Footprint tools
    "export_gerber": {
        "name": "export_gerber",
        "description": "Generate Gerber RS-274X files for a design",
        "fn": tool_export_gerber,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
            "output_dir": {"type": "string", "description": "Optional output directory for Gerber files"},
            "approval_id": {"type": "string", "description": "External approval or release gate identifier"},
        },
    },
    "export_excellon": {
        "name": "export_excellon",
        "description": "Generate Excellon drill files for a design",
        "fn": tool_export_excellon,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
            "output_dir": {"type": "string", "description": "Optional output directory for drill files"},
            "approval_id": {"type": "string", "description": "External approval or release gate identifier"},
        },
    },
    "drc_run": {
        "name": "drc_run",
        "description": "Run Design Rule Check on a design, optionally against a manufacturer fab profile",
        "fn": tool_drc_run,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
            "fab_profile": {
                "type": "string",
                "description": "Optional fab profile name (e.g. 'jlcpcb-2layer') for profile-specific DRC",
            },
        },
    },
    "drc_get_result": {
        "name": "drc_get_result",
        "description": "Get the latest DRC result for a design",
        "fn": tool_drc_get_result,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
        },
    },
    "drc_list_rules": {
        "name": "drc_list_rules",
        "description": "List all DRC rules with descriptions",
        "fn": tool_drc_list_rules,
        "params": {},
    },
    "mechanical_review": {
        "name": "mechanical_review",
        "description": "Review mounting holes vs board size and edges (mechanical / enclosure)",
        "fn": tool_mechanical_review,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
        },
    },
    "security_review": {
        "name": "security_review",
        "description": "Review hardware-security exposure (debug access, secure element, etc.)",
        "fn": tool_security_review,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
        },
    },
    "testability_report": {
        "name": "testability_report",
        "description": "Assess test-point coverage, debug/reset access, and a bring-up checklist",
        "fn": tool_testability_report,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
        },
    },
    "electrical_analysis": {
        "name": "electrical_analysis",
        "description": "Heuristic SI/PI/thermal pre-check (impedance, length-match, PDN, thermal)",
        "fn": tool_electrical_analysis,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
        },
    },
    "requirements_parse": {
        "name": "requirements_parse",
        "description": "Extract structured, machine-readable requirements from a design intent",
        "fn": tool_requirements_parse,
        "params": {
            "intent": {"type": "string", "description": "Design intent description"},
        },
    },
    "requirements_review": {
        "name": "requirements_review",
        "description": "Approve a design's unspecified assumptions and gate on any still pending",
        "fn": tool_requirements_review,
        "params": {
            "intent": {"type": "string", "description": "Design intent description"},
            "approvals": {
                "type": "object",
                "description": 'Map of assumption field -> reviewer decision, e.g. {"rails_v": "3.3V"}',
            },
        },
    },
    "power_tree_plan": {
        "name": "power_tree_plan",
        "description": "Plan a justified power tree (sources, charger, power-path, per-rail regulators) from an intent",
        "fn": tool_power_tree_plan,
        "params": {
            "intent": {"type": "string", "description": "Design intent description"},
        },
    },
    "synthesize_power_tree": {
        "name": "synthesize_power_tree",
        "description": "Emit a real netlist (USB-C CC, regulators, I2C pull-ups) for an intent's power tree",
        "fn": tool_synthesize_power_tree,
        "params": {
            "intent": {"type": "string", "description": "Design intent description"},
            "session_id": {"type": "string", "description": "Session identifier"},
        },
    },
    "synthesize_and_check": {
        "name": "synthesize_and_check",
        "description": "Synthesize an intent's power tree into a netlist and run ERC on it in one step",
        "fn": tool_synthesize_and_check,
        "params": {
            "intent": {"type": "string", "description": "Design intent description"},
            "session_id": {"type": "string", "description": "Session identifier"},
        },
    },
    "board_plan": {
        "name": "board_plan",
        "description": "Plan a justified board block graph (power + interface support) from an intent",
        "fn": tool_board_plan,
        "params": {
            "intent": {"type": "string", "description": "Design intent description"},
        },
    },
    "synthesize_board": {
        "name": "synthesize_board",
        "description": "Emit a real netlist for an intent's whole board via block composition and store it",
        "fn": tool_synthesize_board,
        "params": {
            "intent": {"type": "string", "description": "Design intent description"},
            "session_id": {"type": "string", "description": "Session identifier"},
        },
    },
    "synthesize_board_and_check": {
        "name": "synthesize_board_and_check",
        "description": "Synthesize an intent's whole board into a netlist and run ERC on it in one step",
        "fn": tool_synthesize_board_and_check,
        "params": {
            "intent": {"type": "string", "description": "Design intent description"},
            "session_id": {"type": "string", "description": "Session identifier"},
        },
    },
    "synthesize_board_repair": {
        "name": "synthesize_board_repair",
        "description": "Synthesize a board then run the convergent ERC -> patch -> re-verify self-correction loop",
        "fn": tool_synthesize_board_repair,
        "params": {
            "intent": {"type": "string", "description": "Design intent description"},
            "session_id": {"type": "string", "description": "Session identifier"},
        },
    },
    "synthesize_board_manufacture": {
        "name": "synthesize_board_manufacture",
        "description": "Synthesize a board from intent and emit a manufacturing bundle, evidence, and review checklist",
        "fn": tool_synthesize_board_manufacture,
        "params": {
            "intent": {"type": "string", "description": "Design intent description"},
            "output_dir": {"type": "string", "description": "Directory to write manufacturing artifacts"},
            "session_id": {"type": "string", "description": "Session identifier"},
        },
    },
    "synthesis_benchmark": {
        "name": "synthesis_benchmark",
        "description": "Synthesize a fixed corpus of board types and report aggregate completeness across the engine",
        "fn": tool_synthesis_benchmark,
        "params": {},
    },
    "synthesize_board_score": {
        "name": "synthesize_board_score",
        "description": "Synthesize a board end to end and score its completeness (0-100) across four dimensions",
        "fn": tool_synthesize_board_score,
        "params": {
            "intent": {"type": "string", "description": "Design intent description"},
            "session_id": {"type": "string", "description": "Session identifier"},
        },
    },
    "resolve_footprints": {
        "name": "resolve_footprints",
        "description": "Attach real IPC-7351 pad geometry to a stored design's components (reports gaps)",
        "fn": tool_resolve_footprints,
        "params": {
            "design_name": {"type": "string", "description": "Design name"},
            "session_id": {"type": "string", "description": "Session identifier"},
        },
    },
    "dc_bias_check": {
        "name": "dc_bias_check",
        "description": "Check power-rail DC bias on a stored design and flag undriven rails (always available)",
        "fn": tool_dc_bias_check,
        "params": {
            "design_name": {"type": "string", "description": "Design name"},
            "session_id": {"type": "string", "description": "Session identifier"},
        },
    },
    "simulation_gate": {
        "name": "simulation_gate",
        "description": "Run the DC operating-point simulation gate on a stored design (skip-aware, strict-blocking)",
        "fn": tool_simulation_gate,
        "params": {
            "design_name": {"type": "string", "description": "Design name"},
            "strict": {"type": "boolean", "description": "Treat a skipped simulation as blocking"},
            "session_id": {"type": "string", "description": "Session identifier"},
        },
    },
    "compliance_checklist": {
        "name": "compliance_checklist",
        "description": "Produce a product-class compliance pre-check checklist for a design intent",
        "fn": tool_compliance_checklist,
        "params": {
            "intent": {"type": "string", "description": "Design intent description"},
        },
    },
    "board_classify_nets": {
        "name": "board_classify_nets",
        "description": "Classify all nets in a design using EE knowledge",
        "fn": tool_board_classify_nets,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
        },
    },
    "board_summarize_nets": {
        "name": "board_summarize_nets",
        "description": "Get a summary of all nets and their classifications",
        "fn": tool_board_summarize_nets,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
        },
    },
    "design_route_smart": {
        "name": "design_route_smart",
        "description": "Route all nets with net-class-aware trace widths",
        "fn": tool_design_route_smart,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
            "layer": {"type": "string", "description": "Layer name (default: F.Cu)"},
        },
    },
    "design_classify_nets": {
        "name": "design_classify_nets",
        "description": "Classify all nets in a design by name and pin type",
        "fn": tool_design_classify_nets,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
        },
    },
    "footprint_search": {
        "name": "footprint_search",
        "description": "Search for footprints in the library by keyword",
        "fn": tool_footprint_search,
        "params": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "description": "Max results (default 10)"},
        },
    },
    "footprint_get": {
        "name": "footprint_get",
        "description": "Get footprint details for a library component",
        "fn": tool_footprint_get,
        "params": {
            "component_id": {"type": "string", "description": "Component ID"},
        },
    },
    # Transaction safety — snapshot / rollback tools
    "design_snapshot": {
        "name": "design_snapshot",
        "description": "Capture a point-in-time snapshot of a design for later rollback",
        "fn": tool_design_snapshot,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name to snapshot"},
            "label": {"type": "string", "description": "Optional label for the snapshot (auto-generated if omitted)"},
        },
    },
    "design_rollback": {
        "name": "design_rollback",
        "description": "Restore a design from a named snapshot (reverts all mutations)",
        "fn": tool_design_rollback,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name to rollback"},
            "label": {"type": "string", "description": "Snapshot label to restore from"},
        },
    },
    "design_list_snapshots": {
        "name": "design_list_snapshots",
        "description": "List available snapshots for a design (or all designs in session)",
        "fn": tool_design_list_snapshots,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Optional design name filter"},
        },
    },
    "design_commit": {
        "name": "design_commit",
        "description": "Confirm design changes by clearing snapshots for a design",
        "fn": tool_design_commit,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name to commit"},
            "label": {"type": "string", "description": "Optional snapshot label to commit (omitting clears all)"},
        },
    },
    "design_transaction_preview": {
        "name": "design_transaction_preview",
        "description": "Preview a design mutation as an isolated transaction without committing it",
        "fn": tool_design_transaction_preview,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
            "operation": {"type": "string", "description": "Operation: board_update, component_add, component_remove"},
            "params": {"type": "object", "description": "Operation parameters"},
            "reason": {"type": "string", "description": "Why this transaction is proposed"},
        },
    },
    "design_transaction_validate": {
        "name": "design_transaction_validate",
        "description": "Validate a preview transaction without mutating primary state",
        "fn": tool_design_transaction_validate,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "transaction_id": {"type": "string", "description": "Transaction identifier"},
        },
    },
    "design_transaction_commit": {
        "name": "design_transaction_commit",
        "description": "Commit a validated transaction after explicit approval",
        "fn": tool_design_transaction_commit,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "transaction_id": {"type": "string", "description": "Transaction identifier"},
            "approval_id": {"type": "string", "description": "External approval or release gate identifier"},
        },
    },
    "design_transaction_rollback": {
        "name": "design_transaction_rollback",
        "description": "Reject or roll back a preview transaction without changing primary state",
        "fn": tool_design_transaction_rollback,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "transaction_id": {"type": "string", "description": "Transaction identifier"},
        },
    },
    "design_transaction_list": {
        "name": "design_transaction_list",
        "description": "List transactions for a session",
        "fn": tool_design_transaction_list,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
        },
    },
    "board_export": {
        "name": "board_export",
        "description": "Export the board definition for a design as a JSON description",
        "fn": tool_board_export,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
        },
    },
    # Phase 2 — Schematic, footprint generation, manufacturing
    "schematic_render": {
        "name": "schematic_render",
        "description": "Render a design as an SVG schematic",
        "fn": tool_schematic_render,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
        },
    },
    "footprint_generate": {
        "name": "footprint_generate",
        "description": "Generate a parametric footprint for a given package name",
        "fn": tool_footprint_generate,
        "params": {
            "package": {"type": "string", "description": "Package name (e.g. 0603, SOIC-8, QFN-32)"},
            "layer": {"type": "string", "description": "Layer (top or bottom, default top)"},
        },
    },
    "footprint_list_packages": {
        "name": "footprint_list_packages",
        "description": "List all supported package names for footprint generation",
        "fn": tool_footprint_list_packages,
        "params": {},
    },
    "export_manufacturing": {
        "name": "export_manufacturing",
        "description": "Generate a complete manufacturing package (Gerber + drill + BOM + PnP ZIP)",
        "fn": tool_export_manufacturing,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
            "output_dir": {"type": "string", "description": "Output directory for manufacturing files"},
            "approval_id": {"type": "string", "description": "External approval or release gate identifier"},
        },
    },
    "export_pick_and_place": {
        "name": "export_pick_and_place",
        "description": "Generate a pick-and-place (centroid) CSV for assembly",
        "fn": tool_export_pick_and_place,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
            "approval_id": {"type": "string", "description": "External approval or release gate identifier"},
        },
    },
    "proof_run": {
        "name": "proof_run",
        "description": "Run a Proof Pack from a proof.yaml file or directory to validate a design",
        "fn": tool_proof_run,
        "params": {
            "path": {"type": "string", "description": "Path to proof.yaml or directory containing proof.yaml"},
        },
    },
    "proof_run_design": {
        "name": "proof_run_design",
        "description": "Run proof checks directly against a design in the current session (no proof.yaml needed)",
        "fn": tool_proof_run_design,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Name of the design to validate"},
            "checks": {
                "type": "array",
                "description": "Optional check definitions (name, type, severity, params). Default: structural checks",
            },
        },
    },
    "proof_list_checks": {
        "name": "proof_list_checks",
        "description": "List all checks defined in a Proof Pack without running them",
        "fn": tool_proof_list_checks,
        "params": {
            "path": {"type": "string", "description": "Path to proof.yaml or directory containing proof.yaml"},
        },
    },
    "audit_list_events": {
        "name": "audit_list_events",
        "description": "List recent security/audit events for a session",
        "fn": tool_audit_list_events,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "limit": {"type": "integer", "description": "Maximum number of events to return"},
        },
    },
    "export_spice": {
        "name": "export_spice",
        "description": "Export a design as a SPICE netlist string (foundation for simulation)",
        "fn": tool_export_spice,
        "params": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "design_name": {"type": "string", "description": "Design name"},
        },
    },
    "calc_led_resistor": {
        "name": "calc_led_resistor",
        "description": "Size an LED current-limiting resistor (E-series; current stays at/under target)",
        "fn": tool_calc_led_resistor,
        "params": {
            "supply_v": {"type": "number", "description": "Supply voltage driving the LED + resistor"},
            "forward_v": {"type": "number", "description": "LED forward voltage (Vf)"},
            "current_ma": {"type": "number", "description": "Target forward current in mA"},
            "series": {"type": "integer", "description": "E-series to snap to (12 or 24)"},
        },
    },
    "calc_voltage_divider": {
        "name": "calc_voltage_divider",
        "description": "Choose a divider top resistor for a target output voltage (E-series)",
        "fn": tool_calc_voltage_divider,
        "params": {
            "input_v": {"type": "number", "description": "Divider input voltage"},
            "output_v": {"type": "number", "description": "Target output voltage"},
            "r_bottom": {"type": "number", "description": "Fixed bottom resistor in ohms"},
            "series": {"type": "integer", "description": "E-series to snap to (12 or 24)"},
        },
    },
    "calc_rc_filter": {
        "name": "calc_rc_filter",
        "description": "Compute the -3 dB cutoff frequency of a first-order RC filter",
        "fn": tool_calc_rc_filter,
        "params": {
            "r_ohms": {"type": "number", "description": "Resistance in ohms"},
            "c_farads": {"type": "number", "description": "Capacitance in farads"},
        },
    },
    "calc_i2c_pullup": {
        "name": "calc_i2c_pullup",
        "description": "Compute I2C pull-up range and a recommended value (NXP UM10204)",
        "fn": tool_calc_i2c_pullup,
        "params": {
            "supply_v": {"type": "number", "description": "Bus supply voltage (Vdd)"},
            "bus_capacitance_pf": {"type": "number", "description": "Total bus capacitance in pF"},
            "bus_speed_hz": {"type": "integer", "description": "Bus speed: 100000, 400000, or 1000000"},
            "series": {"type": "integer", "description": "E-series to snap to (12 or 24)"},
        },
    },
    "calc_e_series": {
        "name": "calc_e_series",
        "description": "Snap a value to an E-series preferred value (mode: nearest|ceil|floor)",
        "fn": tool_calc_e_series,
        "params": {
            "value": {"type": "number", "description": "Value to snap"},
            "series": {"type": "integer", "description": "E-series (12 or 24)"},
            "mode": {"type": "string", "description": "nearest | ceil | floor"},
        },
    },
    "calc_usb_c_cc": {
        "name": "calc_usb_c_cc",
        "description": "Resolve the USB-C CC-pin termination resistor for a port role (USB-C spec)",
        "fn": tool_calc_usb_c_cc,
        "params": {
            "role": {"type": "string", "description": "Port role: sink/ufp or source/dfp"},
            "advertised_current_a": {
                "type": "number",
                "description": "For a source, current to advertise at 5V (default USB power if omitted)",
            },
        },
    },
    "calc_decoupling": {
        "name": "calc_decoupling",
        "description": "Plan decoupling/bypass caps for a rail (100 nF per power pin + bulk, derated rating)",
        "fn": tool_calc_decoupling,
        "params": {
            "power_pins": {"type": "integer", "description": "Number of power pins to bypass"},
            "rail_v": {"type": "number", "description": "Rail voltage feeding the pins"},
            "bulk_uf": {"type": "number", "description": "Bulk capacitance in uF (default 10)"},
        },
    },
    "calc_lipo_charge": {
        "name": "calc_lipo_charge",
        "description": "Size the MCP73831/2 PROG resistor for a Li-ion/Li-Po charge current",
        "fn": tool_calc_lipo_charge,
        "params": {
            "charge_current_ma": {"type": "number", "description": "Target charge current in mA (100-500)"},
            "series": {"type": "integer", "description": "E-series to snap onto (12 or 24)"},
        },
    },
    "calc_buck_lc": {
        "name": "calc_buck_lc",
        "description": "Size a buck converter's inductor + output capacitor (CCM) from Vin/Vout/Iout/Fsw",
        "fn": tool_calc_buck_lc,
        "params": {
            "vin": {"type": "number", "description": "Input voltage"},
            "vout": {"type": "number", "description": "Output voltage (< vin)"},
            "iout": {"type": "number", "description": "Maximum load current (A)"},
            "f_sw_hz": {"type": "number", "description": "Switching frequency (Hz)"},
            "ripple_ratio": {"type": "number", "description": "Inductor ripple as fraction of Iout (default 0.3)"},
            "output_ripple_v": {"type": "number", "description": "Allowed output ripple V (default 1% of Vout)"},
        },
    },
}


def _apply_tool_capabilities() -> None:
    """Ensure every public tool declares its required runtime capability."""
    for tool_name, tool_def in TOOL_REGISTRY.items():
        tool_def.setdefault("capability", required_tool_capability(tool_name))


_apply_tool_capabilities()


def get_tool(name: str) -> dict[str, Any]:
    """Get a tool definition by name."""
    if name not in TOOL_REGISTRY:
        raise KeyError(f"Tool '{name}' not found. Available: {list(TOOL_REGISTRY)}")
    return TOOL_REGISTRY[name]


def list_tools() -> list[dict[str, Any]]:
    """List all registered tools (without the function reference)."""
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "params": t["params"],
            "capability": t.get("capability", "read"),
        }
        for t in TOOL_REGISTRY.values()
    ]


def call_tool(name: str, /, **kwargs: Any) -> Any:
    """Call a tool by name with keyword arguments.

    Sandbox checks are applied before execution:
    - Tool-call budget (call count & duration)
    - Dangerous-action classification
    - Prompt-injection detection on string params
    - Secret redaction on params
    Each call is recorded to the replayable session log.
    """
    import time

    from zaptrace.security.replay import record_tool_call
    from zaptrace.security.sandbox import (
        check_tool_budget,
        classify_tool_call,
        detect_prompt_injection,
        redact_secrets,
    )

    session_id = kwargs.get("session_id", "default")

    # ---- 1. Tool-call budget check ----
    check_tool_budget(session_id, name)

    # ---- 2. Scan string params for prompt injection ----
    for param_key, param_val in kwargs.items():
        if isinstance(param_val, str):
            findings = detect_prompt_injection(param_val)
            if findings:
                patterns = [f["pattern"] for f in findings]
                raise ValueError(
                    f"Prompt injection detected in parameter '{param_key}' (patterns: {patterns}). Tool call blocked."
                )

    # ---- 3. Classify action risk ----
    risk = classify_tool_call(session_id, name, kwargs)

    # ---- 4. Redact secrets from kwargs (for logging) ----
    safe_params = {}
    for k, v in kwargs.items():
        safe_params[k] = redact_secrets(v) if isinstance(v, str) else v

    # ---- 5. Execute the tool ----
    tool_def = get_tool(name)
    t0 = time.perf_counter()
    try:
        result = tool_def["fn"](**kwargs)
    except Exception as exc:
        # Record failed call too
        elapsed = (time.perf_counter() - t0) * 1000
        record_tool_call(
            session_id,
            name,
            safe_params,
            result={"error": str(exc)},
            duration_ms=elapsed,
            risk=risk.value,
        )
        raise

    elapsed = (time.perf_counter() - t0) * 1000

    # ---- 6. Record to replay log ----
    record_tool_call(
        session_id,
        name,
        safe_params,
        result=result,
        duration_ms=elapsed,
        risk=risk.value,
    )

    return result
