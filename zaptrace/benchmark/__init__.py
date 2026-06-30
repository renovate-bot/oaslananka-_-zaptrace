"""Benchmark corpus package."""

from zaptrace.benchmark.corpus import (
    BUILTIN_BENCHMARKS,
    BenchmarkCriterion,
    BenchmarkEntry,
    BenchmarkResult,
    BenchmarkRunResult,
    get_benchmark,
    list_benchmarks,
)
from zaptrace.benchmark.families import (
    AcceptanceThreshold,
    BenchmarkBoardFamily,
    BoardFamilyManifest,
    RequiredBenchmarkArtifact,
    builtin_board_family_manifest,
    get_board_family,
    list_board_families,
    load_board_family_manifest,
    manifest_json,
    validate_board_family_manifest,
)
from zaptrace.benchmark.kicad_fixtures import (
    GoldenKiCadComparisonResult,
    GoldenKiCadFile,
    GoldenKiCadProjectFixture,
    build_golden_kicad_fixture,
    compare_golden_kicad_fixture,
    compute_kicad_file_record,
    load_golden_kicad_fixture,
)

__all__ = [
    "BUILTIN_BENCHMARKS",
    "BenchmarkCriterion",
    "BenchmarkEntry",
    "BenchmarkResult",
    "BenchmarkRunResult",
    "get_benchmark",
    "list_benchmarks",
    "GoldenKiCadComparisonResult",
    "GoldenKiCadFile",
    "GoldenKiCadProjectFixture",
    "build_golden_kicad_fixture",
    "compare_golden_kicad_fixture",
    "compute_kicad_file_record",
    "load_golden_kicad_fixture",
    "AcceptanceThreshold",
    "BenchmarkBoardFamily",
    "BoardFamilyManifest",
    "RequiredBenchmarkArtifact",
    "builtin_board_family_manifest",
    "get_board_family",
    "list_board_families",
    "load_board_family_manifest",
    "manifest_json",
    "validate_board_family_manifest",
]
