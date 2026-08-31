"""Regression coverage for the scheduled catalog maintenance workflow."""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/catalog-maintenance.yml")


def test_catalog_maintenance_installs_every_tested_python_package():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["maintenance-report"]["steps"]
    install = next(step for step in steps if step.get("name") == "Install test dependencies")
    command = install["run"]

    assert 'pip install -e ".[dev]"' in command
    assert 'pip install -e "./services/openva_match_service[dev]"' in command


def test_catalog_maintenance_remains_non_mutating():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert workflow["permissions"] == {"contents": "read", "actions": "read"}
