from __future__ import annotations

import re
from pathlib import Path


def test_docker_python_version_is_covered_by_ci_matrix() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")
    image_versions = set(re.findall(r"FROM python:(\d+\.\d+)-slim", dockerfile))
    assert image_versions
    assert len(image_versions) == 1
    matrix_versions = set(re.findall(r'"(3\.\d+)"', workflow))
    assert image_versions <= matrix_versions


def test_docker_runtime_bundles_ngspice_for_simulation_gate() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "ngspice" in dockerfile
