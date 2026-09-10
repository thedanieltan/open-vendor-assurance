from __future__ import annotations

import copy

import yaml

from tools.openva.discovery_mesh_intake import yaml_text


def test_yaml_text_truncates_candidate_page_title_to_schema_limit_without_mutating_input():
    candidate = {
        "candidate_source_id": "example-dpa-123",
        "vendor_id": "example",
        "evidence": {"page_title": "x" * 350, "matched_terms": ["privacy"]},
    }
    original = copy.deepcopy(candidate)

    rendered = yaml.safe_load(yaml_text(candidate))

    assert candidate == original
    assert rendered["evidence"]["page_title"] == "x" * 300


def test_yaml_text_leaves_valid_page_title_unchanged():
    candidate = {
        "candidate_source_id": "example-dpa-123",
        "vendor_id": "example",
        "evidence": {"page_title": "Data Processing Agreement", "matched_terms": []},
    }

    rendered = yaml.safe_load(yaml_text(candidate))

    assert rendered["evidence"]["page_title"] == "Data Processing Agreement"
