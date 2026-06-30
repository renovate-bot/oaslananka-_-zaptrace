"""Proof Pack — self-verifying design validation packages.

A Proof Pack is a portable, self-contained validation bundle that proves a PCB design
is manufacturable. It includes: design constraints, expected outputs, pass/fail criteria,
and optionally reference files (golden outputs).

Usage:
    from zaptrace.proof import ProofPack, run_proof

    pack = ProofPack.load("path/to/proof.yaml")
    results = pack.run()
    results.summary()  # "PASS: 12/12 checks"
"""

from __future__ import annotations

from .checker import CheckResult, CheckStatus, ProofRunner
from .manifest import (
    ArtifactRecord,
    CheckDefinition,
    CheckRecord,
    CheckSource,
    EnvironmentRecord,
    InputRecord,
    ManifestModel,
    ProofManifest,
)
from .manifest import (
    CheckStatus as ManifestCheckStatus,
)
from .pack import ProofPack, capture_environment, hash_file, run_proof, validate_proof_pack
from .signoff import (
    AutonomousSignoffDecision,
    AutonomousSignoffPolicy,
    AutonomousSignoffStatus,
    SignoffCheckStatus,
    SignoffEvidence,
)

__all__ = [
    "ProofManifest",
    "ManifestModel",
    "CheckDefinition",
    "CheckRecord",
    "CheckSource",
    "ArtifactRecord",
    "EnvironmentRecord",
    "InputRecord",
    "ProofRunner",
    "CheckResult",
    "CheckStatus",
    "ManifestCheckStatus",
    "ProofPack",
    "run_proof",
    "validate_proof_pack",
    "capture_environment",
    "hash_file",
    "AutonomousSignoffStatus",
    "SignoffCheckStatus",
    "SignoffEvidence",
    "AutonomousSignoffDecision",
    "AutonomousSignoffPolicy",
]
