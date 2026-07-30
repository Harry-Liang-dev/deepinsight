"""Foundation environment tests."""

from __future__ import annotations

import importlib.util
import sys


def test_python_version_is_312() -> None:
    """Verify that tests run with the supported Python interpreter."""
    assert sys.version_info[:2] == (3, 12)


def test_project_packages_are_importable() -> None:
    """Verify that the scaffold packages are discoverable."""
    package_names = (
        "apps",
        "apps.api",
        "apps.scheduler",
        "apps.web",
        "apps.worker",
        "src",
        "src.adapters",
        "src.agents",
        "src.api",
        "src.core",
        "src.memory",
        "src.models",
        "src.operators",
        "src.orchestration",
        "src.phase2_reserved",
        "src.reports",
        "src.repositories",
        "src.schemas",
        "src.services",
    )
    for package_name in package_names:
        assert importlib.util.find_spec(package_name) is not None


def test_runtime_dependencies_are_installed() -> None:
    """Verify that declared Phase One runtime dependencies are discoverable."""
    module_names = (
        "apscheduler",
        "duckdb",
        "faiss",
        "fastapi",
        "openai",
        "pandas",
        "pydantic",
        "pydantic_settings",
        "sqlalchemy",
        "streamlit",
        "structlog",
        "uvicorn",
        "yaml",
    )
    missing = [name for name in module_names if importlib.util.find_spec(name) is None]
    assert not missing, f"Missing runtime dependencies: {missing}"
