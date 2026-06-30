"""Manufacturing export — Gerber ZIP, pick-and-place, BOM, drill, and manifest.

Generates a complete, JLCPCB-ready manufacturing package from a ``Design``.
"""

from __future__ import annotations

import csv
import json
import re
import zipfile
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

from zaptrace import __version__
from zaptrace.core.board import canonical_board_definition
from zaptrace.core.models import Design
from zaptrace.export.bom import generate_bom_csv
from zaptrace.export.excellon import generate_composite_drill, generate_excellon
from zaptrace.export.gerber import generate_gerber
from zaptrace.export.ipcd356 import write_ipcd356

# ---------------------------------------------------------------------------
#  Pick-and-place (centroid) CSV
# ---------------------------------------------------------------------------


def _component_side(comp: Any) -> str:
    """Determine which side of the board a component is placed on.

    Defaults to "top". THT components and components with all-layer pads
    are marked "top". Bottom-side placement is inferred from position
    heuristics or a dedicated property.
    """
    if comp.properties and comp.properties.get("side") in ("bottom", "top"):
        return comp.properties["side"]
    if comp.footprint_def:
        pads_on_bottom = sum(1 for p in comp.footprint_def.pads if p.layer.value == "bottom")
        pads_on_top = sum(1 for p in comp.footprint_def.pads if p.layer.value == "top")
        if pads_on_bottom > pads_on_top:
            return "bottom"
    return "top"


def generate_pick_and_place(design: Design) -> str:
    """Generate a pick-and-place (centroid) CSV file for SMD assembly.

    Columns:
        Ref, Value, Package, PosX (mm), PosY (mm), Rotation (deg), Side
    """
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Ref", "Value", "Package", "PosX", "PosY", "Rotation", "Side"])

    placement = design.placement or {}

    for comp in sorted(design.components.values(), key=lambda c: c.ref):
        pos = placement.get(comp.id)
        if pos is None and comp.position is not None:
            pos = comp.position
        if pos is None:
            continue

        x, y = pos
        rotation = 0.0
        if comp.properties:
            rotation = float(comp.properties.get("rotation", 0.0))

        pkg = comp.footprint or ""
        side = _component_side(comp)

        writer.writerow(
            [
                comp.ref,
                comp.value or "",
                pkg,
                f"{x:.3f}",
                f"{y:.3f}",
                f"{rotation:.1f}",
                side,
            ]
        )

    return output.getvalue()


# ---------------------------------------------------------------------------
#  Manufacturing manifest
# ---------------------------------------------------------------------------


def generate_manufacturing_manifest(design: Design) -> str:
    """Generate a JSON manifest describing the manufacturing output.

    Includes design metadata, layer stack, component count, net count, and
    file listing.
    """
    board = canonical_board_definition(design)
    bw = board.width
    bh = board.height
    layers = board.layers

    manifest: dict[str, Any] = {
        "design": {
            "name": design.meta.name,
            "version": design.meta.version,
            "author": design.meta.author,
            "revision": design.meta.revision,
            "description": design.meta.description,
            "generated_at": datetime.now(UTC).isoformat(),
        },
        "board": {
            "width_mm": bw,
            "height_mm": bh,
            "layers": layers,
            "copper_pour_gnd": board.copper_pour_gnd,
        },
        "statistics": {
            "components": len(design.components),
            "nets": len(design.nets),
            "placed_components": sum(
                1 for c in design.components.values() if design.placement and c.id in design.placement
            ),
        },
        "output_files": [
            {
                "file": ".GTL",
                "layer": "Top copper",
                "description": "Top signal layer",
            },
            {
                "file": ".GBL",
                "layer": "Bottom copper",
                "description": "Bottom signal layer",
            },
            {
                "file": ".GTO",
                "layer": "Top overlay",
                "description": "Top silkscreen",
            },
            {
                "file": ".GTS",
                "layer": "Top solder mask",
                "description": "Top solder mask (green)",
            },
            {
                "file": ".GBS",
                "layer": "Bottom solder mask",
                "description": "Bottom solder mask (green)",
            },
            {
                "file": ".GKO",
                "layer": "Board outline",
                "description": "PCB edge cuts",
            },
            {
                "file": ".GPT",
                "layer": "Top paste",
                "description": "Solder paste stencil",
            },
            {
                "file": ".TXT",
                "layer": "Excellon drill",
                "description": "NC drill file (PTH + NPTH)",
            },
            {
                "file": ".IPC",
                "layer": "Manufacturing netlist",
                "description": "IPC-D-356 connectivity evidence",
            },
        ],
        "tool": "ZapTrace AI-EDA",
        "tool_version": __version__,
    }

    return json.dumps(manifest, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
#  Manufacturing ZIP bundle
# ---------------------------------------------------------------------------


def _safe_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    return re.sub(r"[^\w.-]", "_", name)


def generate_manufacturing_bundle(
    design: Design,
    output_dir: str | Path,
    prefix: str | None = None,
) -> dict[str, Any]:
    """Generate a complete manufacturing package as individual files + ZIP.

    Produces:
        - Gerber files for all 7 layers
        - Excellon drill file (PTH)
        - Excellon drill file (NPTH)
        - Composite drill file
        - BOM CSV
        - Pick-and-place CSV
        - Manufacturing manifest JSON
        - IPC-D-356 manufacturing netlist
        - ``<design>.zip`` containing all of the above

    Args:
        design: The design to export.
        output_dir: Directory to write output files to.
        prefix: Optional filename prefix (defaults to design name).

    Returns:
        Dict of ``{label: file_path | content_string}``.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    pfx = _safe_filename(prefix or design.meta.name or "board")

    result: dict[str, Any] = {}

    # ── Gerber layers ────────────────────────────────────────────────────
    gerber_files = generate_gerber(design, output_dir=str(out), prefix=pfx)
    result["gerber_layers"] = gerber_files

    # ── Excellon drill ───────────────────────────────────────────────────
    drill_files = generate_excellon(design, output_dir=str(out), prefix=pfx)
    for k, v in drill_files.items():
        result[f"drill_{k}"] = v

    # ── Composite drill ──────────────────────────────────────────────────
    composite = generate_composite_drill(design, output_dir=str(out), prefix=pfx)
    if composite:
        result["drill_composite"] = composite

    # ── BOM CSV ──────────────────────────────────────────────────────────
    bom_csv = generate_bom_csv(design)
    bom_path = out / f"{pfx}-bom.csv"
    bom_path.write_text(bom_csv, encoding="utf-8")
    result["bom"] = str(bom_path)

    # ── Pick-and-place CSV ───────────────────────────────────────────────
    pnp_csv = generate_pick_and_place(design)
    pnp_path = out / f"{pfx}-pick-and-place.csv"
    pnp_path.write_text(pnp_csv, encoding="utf-8")
    result["pick_and_place"] = str(pnp_path)

    # ── IPC-D-356 manufacturing netlist ─────────────────────────────────
    ipc_path = write_ipcd356(design, out / f"{pfx}.ipc")
    result["ipc_d356"] = str(ipc_path)

    # ── Manufacturing manifest ───────────────────────────────────────────
    manifest = generate_manufacturing_manifest(design)
    manifest_path = out / f"{pfx}-manifest.json"
    manifest_path.write_text(manifest, encoding="utf-8")
    result["manifest"] = str(manifest_path)

    # ── ZIP bundle ───────────────────────────────────────────────────────
    zip_path = out / f"{pfx}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add Gerber files
        for _layer_name, file_path in gerber_files.items():
            fp = Path(file_path)
            if fp.exists():
                zf.write(fp, arcname=fp.name)

        # Add drill files
        for _k, file_path in drill_files.items():
            fp = Path(file_path)
            if fp.exists():
                zf.write(fp, arcname=fp.name)

        if composite:
            fp = Path(composite)
            if fp.exists():
                zf.write(fp, arcname=fp.name)

        # Add BOM, PnP, manifest
        for label in ("bom", "pick_and_place", "ipc_d356", "manifest"):
            fp = Path(result[label])
            if fp.exists():
                zf.write(fp, arcname=fp.name)

    result["zip"] = str(zip_path)

    return result
