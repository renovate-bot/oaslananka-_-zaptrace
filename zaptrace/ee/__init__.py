"""EE Knowledge Base — embedded electrical engineering rules and defaults."""

from zaptrace.ee.classifier import classify_design, get_net_class, summarize_classification
from zaptrace.ee.constraints.net_classes import CLASS_RULES, NetClass, NetClassRule
from zaptrace.ee.drc import DRCEngine
from zaptrace.ee.footprints import (
    generate_footprint,
    generate_footprint_for_component,
    list_supported_packages,
    symbol_from_pins,
)
from zaptrace.ee.knowledge import KnowledgeBase
from zaptrace.ee.routing.defaults import (
    CLEARANCE_MATRIX,
    DEFAULT_TRACE_WIDTHS,
    DEFAULT_VIA_SPECS,
    STACKUP_PRESETS,
)

__all__ = [
    "KnowledgeBase",
    "NetClass",
    "NetClassRule",
    "CLASS_RULES",
    "CLEARANCE_MATRIX",
    "DEFAULT_TRACE_WIDTHS",
    "DEFAULT_VIA_SPECS",
    "STACKUP_PRESETS",
    "classify_design",
    "get_net_class",
    "summarize_classification",
    "DRCEngine",
    "generate_footprint",
    "generate_footprint_for_component",
    "list_supported_packages",
    "symbol_from_pins",
]
