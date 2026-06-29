"""Specctra DSN export — universal interchange for external autorouters."""

from __future__ import annotations

from zaptrace.core.models import Design, LayerSet
from zaptrace.ee.knowledge import KnowledgeBase
from zaptrace.ee.routing.impedance import ImpedanceResult


def export_dsn(design: Design) -> str:
    """Serialize a Design to a valid Specctra DSN format.

    Args:
        design: The placed design to serialize.

    Returns:
        The complete .dsn file as a string.
    """
    kb = KnowledgeBase()
    # We load a fallback standard preset if the knowledgebase allows it
    # Ideally, KB is already injected with the design context.

    out = []
    out.append(f"(pcb {design.meta.name}")
    out.append("  (parser")
    out.append('    (string_quote ")')
    out.append("    (space_in_quoted_tokens on)")
    out.append('    (host_cad "ZapTrace")')
    out.append('    (host_version "1.0")')
    out.append("  )")
    out.append("  (resolution mm 10000)")
    out.append("  (unit mm)")

    # --- Structure ---
    out.append("  (structure")

    layer_names = []
    # Layer stack
    if design.board_def and design.board_def.layer_stack:
        for layer in design.board_def.layer_stack:
            layer_type = "signal" if layer.type.lower() == "signal" else "power"
            out.append(f"    (layer {layer.name} (type {layer_type}))")
            layer_names.append(layer.name)

    # Board outline
    if design.board_def and design.board_def.outline:
        out.append("    (boundary")
        path_points = []
        for p in design.board_def.outline:
            path_points.append(f"{p[0]:.4f} {p[1]:.4f}")
        # close the outline if it's not closed
        if design.board_def.outline[0] != design.board_def.outline[-1]:
            p = design.board_def.outline[0]
            path_points.append(f"{p[0]:.4f} {p[1]:.4f}")

        out.append(f"      (path pcb 0 {' '.join(path_points)})")
        out.append("    )")

    out.append("  )")

    # --- Placement ---
    out.append("  (placement")

    for comp_id, comp in design.components.items():
        if not comp.footprint_def or not comp.footprint_def.pads:
            continue

        pos_x, pos_y = 0.0, 0.0
        rot = 0.0
        if design.placement and comp_id in design.placement:
            placement_val = design.placement[comp_id]
            if len(placement_val) >= 3:
                pos_x, pos_y, rot = placement_val[0], placement_val[1], placement_val[2]
            else:
                pos_x, pos_y = placement_val[0], placement_val[1]
        elif comp.position:
            pos_x, pos_y = comp.position

        side = "front"
        out.append(f"    (component {comp_id}")
        out.append(f"      (place {comp_id} {pos_x:.4f} {pos_y:.4f} {side} {rot:.1f})")
        out.append("    )")

    out.append("  )")

    # --- Library (components and pads) ---
    out.append("  (library")

    padstacks_generated = {}

    for comp_id, comp in design.components.items():
        if not comp.footprint_def or not comp.footprint_def.pads:
            continue

        out.append(f"    (image {comp_id}")

        for pad in comp.footprint_def.pads:
            layer_name = "F.Cu"  # default
            if layer_names:
                layer_name = layer_names[0]
                if pad.layer == LayerSet.BOTTOM and len(layer_names) > 1:
                    layer_name = layer_names[-1]

            # Format pad name properly so it's unique
            padstack_name = f"Pad_{pad.shape.value}_{pad.size[0]:.2f}x{pad.size[1]:.2f}_{layer_name}".replace(".", "_")
            if padstack_name not in padstacks_generated:
                # Store the definition to output later in the library
                padstacks_generated[padstack_name] = (pad, layer_name)

            out.append(f"      (pin {padstack_name} {pad.id} {pad.position[0]:.4f} {pad.position[1]:.4f})")

        out.append("    )")

    # Output the generated padstacks
    for ps_name, (pad, layer_name) in padstacks_generated.items():
        out.append(f"    (padstack {ps_name}")

        shape_type = pad.shape.value

        if shape_type == "circle":
            radius = pad.size[0] / 2
            shape_str = f"(circle {layer_name} {radius:.4f})"
        else:
            # Default to rect for now, handle oval similarly as rect if needed or a path.
            # DSN doesn't explicitly have oval, commonly approximated with paths or rectangle
            x1, y1 = -pad.size[0] / 2, -pad.size[1] / 2
            x2, y2 = pad.size[0] / 2, pad.size[1] / 2
            shape_str = f"(rect {layer_name} {x1:.4f} {y1:.4f} {x2:.4f} {y2:.4f})"

        out.append(f"      (shape {shape_str})")
        out.append("    )")

    out.append("  )")

    # --- Network (net connectivity) ---
    out.append("  (network")
    for _net_id, net in design.nets.items():
        out.append(f"    (net {net.name}")
        out.append("      (pins")
        for node in net.nodes:
            out.append(f"        {node.component_ref}-{node.pin_name}")
        out.append("      )")
        out.append("    )")
    out.append("  )")

    # --- Wiring / Classes (Routing rules) ---
    out.append("  (wiring")
    for _net_id, net in design.nets.items():
        # Get width and gap from KnowledgeBase
        geom = kb.resolve_net_geometry(net)

        width = 0.2  # default
        gap = None

        if isinstance(geom, ImpedanceResult):
            width = geom.trace_width
            gap = geom.gap
        elif isinstance(geom, dict):
            width = geom.get("trace_width", 0.2)

        # Optional: We could get clearance from kb.get_clearance() based on NetClass
        # But this basic clearance works.
        clearance = 0.15

        out.append(f"    (class {net.name}_Class {net.name}")
        out.append("      (rule")
        out.append(f"        (width {width:.4f})")
        out.append(f"        (clearance {clearance:.4f})")
        if gap is not None:
            # We add custom rules or diff pair rules if gap exists. DSN doesn't natively
            # have a "gap" unless we define a diffpair constraint, but we can set the width.
            # Usually autorouters need a diffpair rule, but here we provide what's required:
            # widths from the computed width.
            pass
        out.append("      )")
        out.append("    )")

    out.append("  )")

    out.append(")")

    return "\n".join(out)
