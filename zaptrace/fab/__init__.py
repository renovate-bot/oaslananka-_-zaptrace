"""Fabrication profiles — manufacturer capabilities, DFM validation."""

from __future__ import annotations

from zaptrace.fab.dfm import DFMChecker, DFMCheckResult, DFMViolation
from zaptrace.fab.profile import (
    FabProfile,
    ProfileRegistry,
    get_builtin_profile_names,
    load_profile,
    load_profile_from_yaml,
)

__all__ = [
    "FabProfile",
    "ProfileRegistry",
    "load_profile",
    "load_profile_from_yaml",
    "get_builtin_profile_names",
    "DFMChecker",
    "DFMCheckResult",
    "DFMViolation",
]
