"""Regression lock: committed candidate-source records match their schema.

WP-OPENVA-DISCOVERY-SCHEMA-ALIGNMENT-01.

The candidate-source schema is the discovery-plane contract. It must accept exactly what
`tools.openva.source_discovery` produces. This test fails closed if the generator and the
schema drift apart again (the failure mode that left 1,416 invalid records on main).
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.openva.validate import validate_schema

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "openva" / "candidate-source.schema.json"


def test_committed_candidate_records_validate():
    assert validate_schema("candidate_source") == []


def test_schema_stays_fail_closed_on_unknown_fields():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    # Unknown top-level and evidence fields must still be rejected.
    assert schema["additionalProperties"] is False
    assert schema["properties"]["evidence"]["additionalProperties"] is False


def test_schema_accepts_the_generator_discovery_methods():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    methods = set(schema["properties"]["discovery_method"]["enum"])
    assert {"sitemap_locator_verification", "rendered_dom_locator_verification"} <= methods
