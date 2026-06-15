import json
from pathlib import Path

import yaml

from tools.openva.source_discovery import DEFAULT_SOURCE_TYPES, SOURCE_TYPE_REGISTRY
from tools.openva.source_verification import SOURCE_TYPE_KEYWORDS


ROOT = Path(__file__).resolve().parents[1]


def enum_values(schema_name: str, property_name: str) -> set[str]:
    schema = json.loads((ROOT / "schemas/openva" / schema_name).read_text(encoding="utf-8"))
    return set(schema["properties"][property_name]["enum"])


def test_automatic_source_type_registry_contract():
    registry_types = set(SOURCE_TYPE_REGISTRY)
    controlled = set(yaml.safe_load((ROOT / "config/controlled-vocabulary.yaml").read_text(encoding="utf-8"))["source_types"])
    candidate_schema = enum_values("candidate-source.schema.json", "source_type_candidate")
    source_schema = enum_values("source-reference.schema.json", "source_type")
    verifier_types = set(SOURCE_TYPE_KEYWORDS)
    policy = yaml.safe_load((ROOT / "config/automerge-policy.yaml").read_text(encoding="utf-8"))
    strict_core = set(policy["strict_growth"]["core_source_types"])
    coverage_required = set(
        yaml.safe_load((ROOT / "config/coverage-targets.yaml").read_text(encoding="utf-8"))["required_source_types"]
    )

    assert set(DEFAULT_SOURCE_TYPES) == registry_types
    assert registry_types <= controlled
    assert registry_types <= candidate_schema
    assert registry_types <= source_schema
    assert registry_types <= verifier_types
    assert coverage_required <= registry_types
    assert strict_core <= {
        source_type
        for source_type, config in SOURCE_TYPE_REGISTRY.items()
        if config["qualifies_for_vendor_materialization"]
    }
    assert SOURCE_TYPE_REGISTRY["status_page"]["qualifies_for_vendor_materialization"] is False
    assert SOURCE_TYPE_REGISTRY["status_page"]["qualifies_as_promotion_source_role"] is False
