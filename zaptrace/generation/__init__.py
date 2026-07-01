"""Board generation pipeline contracts."""

from zaptrace.generation.compiler import (
    CompilationStatus,
    CompiledDesignIR,
    DesignIRCompilationReport,
    RequirementTrace,
    compile_intent_to_design_ir,
    design_ir_compilation_report_json,
    supported_generation_families,
)
from zaptrace.generation.intent import (
    ArtifactPolicy,
    BoardGenerationIntent,
    EvidenceExpectation,
    InterfaceConstraint,
    PowerConstraint,
    RequirementRef,
    board_generation_intent_json,
    load_board_generation_intent,
    minimal_board_generation_intent_example,
    validate_board_generation_intent,
)
from zaptrace.generation.kicad_schematic import (
    GeneratedKiCadSchematicProject,
    GeneratedKiCadSchematicReport,
    GeneratedSchematicArtifact,
    generate_kicad_schematic_project,
    generated_kicad_schematic_report_json,
)

__all__ = [
    "GeneratedKiCadSchematicProject",
    "GeneratedKiCadSchematicReport",
    "GeneratedSchematicArtifact",
    "generate_kicad_schematic_project",
    "generated_kicad_schematic_report_json",
    "CompiledDesignIR",
    "CompilationStatus",
    "DesignIRCompilationReport",
    "RequirementTrace",
    "compile_intent_to_design_ir",
    "design_ir_compilation_report_json",
    "supported_generation_families",
    "ArtifactPolicy",
    "BoardGenerationIntent",
    "EvidenceExpectation",
    "InterfaceConstraint",
    "PowerConstraint",
    "RequirementRef",
    "board_generation_intent_json",
    "load_board_generation_intent",
    "minimal_board_generation_intent_example",
    "validate_board_generation_intent",
]
