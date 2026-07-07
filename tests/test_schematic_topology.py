from __future__ import annotations

import json

from zaptrace.generation import (
    TopologySynthesisStatus,
    compile_electronics_intent_to_architecture,
    compile_intent_to_design_ir,
    convert_architecture_to_board_generation_intent,
    generate_kicad_schematic_project,
    schematic_topology_plan_json,
    synthesize_schematic_topology_plan,
)


def _ready_architecture_intent_compiled():
    architecture = compile_electronics_intent_to_architecture(
        "ESP32 USB-C temperature sensor board with I2C sensor and 3.3V logic rail",
        design_name="esp32_usb_temperature_sensor_architecture_v1",
    )
    intent = convert_architecture_to_board_generation_intent(architecture)
    compiled = compile_intent_to_design_ir(intent)
    return architecture, intent, compiled


def test_synthesize_schematic_topology_plan_from_ready_architecture() -> None:
    architecture, intent, compiled = _ready_architecture_intent_compiled()

    plan = synthesize_schematic_topology_plan(architecture, intent, compiled)

    assert plan.status == TopologySynthesisStatus.SYNTHESIZED
    assert plan.synthesized is True
    assert plan.design_name == intent.design_name
    assert plan.family_id == "esp32_usb_sensor"
    assert plan.source_architecture_status == "ready"
    assert plan.source_compiler_method == "template_selection"
    assert plan.blocking_reasons == []
    assert {block.kind for block in plan.blocks} >= {"mcu", "sensor", "interface"}
    assert any(block.component_refs for block in plan.blocks if block.kind == "mcu")
    assert {interface.name for interface in plan.interfaces} >= {"usb", "i2c"}
    assert {net.name for net in plan.nets} >= {"VCC_3V3", "GND", "I2C_SDA", "I2C_SCL"}
    assert "not fabrication-ready" in " ".join(plan.non_claims)


def test_schematic_topology_plan_json_round_trip() -> None:
    architecture, intent, compiled = _ready_architecture_intent_compiled()
    plan = synthesize_schematic_topology_plan(architecture, intent, compiled)

    payload = json.loads(schematic_topology_plan_json(plan))

    assert payload["schema_version"] == "1.0"
    assert payload["status"] == "synthesized"
    assert payload["method"] == "architecture_topology_planning"
    assert payload["blocks"]
    assert payload["nets"]


def test_non_ready_architecture_blocks_topology_synthesis() -> None:
    architecture = compile_electronics_intent_to_architecture("make a small board")
    _, intent, compiled = _ready_architecture_intent_compiled()

    plan = synthesize_schematic_topology_plan(architecture, intent, compiled)

    assert plan.status == TopologySynthesisStatus.BLOCKED
    assert plan.synthesized is False
    assert plan.blocking_reasons == ["intent is too vague to derive electronics architecture"]
    assert plan.blocks == []
    assert plan.nets == []


def test_generate_kicad_schematic_project_with_topology_plan(tmp_path) -> None:
    architecture, intent, compiled = _ready_architecture_intent_compiled()
    plan = synthesize_schematic_topology_plan(architecture, intent, compiled)

    generated = generate_kicad_schematic_project(compiled, tmp_path, topology_plan=plan)

    topology_path = tmp_path / f"{compiled.design.meta.name}.schematic_topology.json"
    payload = json.loads(generated.report_path.read_text(encoding="utf-8"))

    assert topology_path.is_file()
    assert generated.report.topology_present is True
    assert generated.report.topology_status == "synthesized"
    assert generated.report.topology_block_count == len(plan.blocks)
    assert generated.report.topology_net_count == len(plan.nets)
    assert "topology-plan" in {artifact.kind for artifact in generated.report.generated_files}
    assert payload["topology_present"] is True
    assert payload["topology_status"] == "synthesized"
