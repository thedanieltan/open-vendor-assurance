"""Drift tests for the definitive source-type vocabulary and its labels.

The machine identifiers in schemas/openva/source-reference.schema.json and
config/controlled-vocabulary.yaml are compatibility-sensitive and stay
stable. Exactly one authoritative human-facing label mapping exists
(config/controlled-vocabulary.yaml -> source_type_labels), and every
human-facing surface derives its wording from it.
"""

import json
import re
from pathlib import Path

import pytest
import yaml

from tools.openva.source_type_labels import source_type_label, source_type_labels

ROOT = Path(__file__).resolve().parents[1]

# The frozen product vocabulary: machine key -> full human-facing label.
EXPECTED_LABELS = {
    "dpa": "Data processing addendum",
    "subprocessors_list": "Subprocessor list",
    "privacy_notice": "Privacy notice",
    "trust_center": "Trust center",
    "security_page": "Security page",
    "compliance_page": "Compliance page",
    "certification_reference": "Certification reference",
    "terms_of_service": "Terms of service",
    "kyc_statement": "Know your customer statement",
    "aml_statement": "Anti-money laundering statement",
    "ai_terms": "Artificial intelligence terms",
    "government_request_policy": "Government request policy",
    "transparency_report": "Transparency report",
    "status_page": "Service status page",
    "other_public_source": "Other public source",
}


def schema_source_types() -> set[str]:
    schema = json.loads(
        (ROOT / "schemas/openva/source-reference.schema.json").read_text(encoding="utf-8")
    )
    return set(schema["properties"]["source_type"]["enum"])


def vocabulary() -> dict:
    return yaml.safe_load(
        (ROOT / "config/controlled-vocabulary.yaml").read_text(encoding="utf-8")
    )


def test_machine_identifiers_remain_backwards_compatible():
    assert schema_source_types() == set(EXPECTED_LABELS)
    assert set(vocabulary()["source_types"]) == set(EXPECTED_LABELS)


def test_every_schema_source_type_has_exactly_one_full_label():
    labels = source_type_labels()
    assert labels == EXPECTED_LABELS
    assert set(labels) == schema_source_types()


def test_labels_use_full_terminology_not_bare_acronyms():
    for key, label in source_type_labels().items():
        assert label.strip(), f"blank label for {key}"
        # A label must never be an unexplained all-caps acronym like "DPA".
        assert not re.fullmatch(r"[A-Z]{2,}", label), f"acronym-only label for {key}: {label}"
        for word in label.split():
            assert not re.fullmatch(r"[A-Z]{2,}", word), (
                f"label for {key} contains unexplained acronym: {label}"
            )


def test_label_accessor_falls_back_to_machine_key_for_unknown_types():
    assert source_type_label("dpa") == "Data processing addendum"
    assert source_type_label("nonexistent_type") == "nonexistent_type"


def test_vocabulary_accessor_raises_on_drift(tmp_path, monkeypatch):
    import tools.openva.source_type_labels as module

    drifted = tmp_path / "controlled-vocabulary.yaml"
    vocab = vocabulary()
    vocab["source_type_labels"].pop("dpa")
    drifted.write_text(yaml.safe_dump(vocab), encoding="utf-8")
    monkeypatch.setattr(module, "_VOCAB_PATH", drifted)
    module._vocabulary.cache_clear()
    try:
        with pytest.raises(ValueError, match="missing a human-facing label"):
            module.source_type_labels()
    finally:
        module._vocabulary.cache_clear()


def test_catalog_records_stay_inside_the_vocabulary():
    recorded = set()
    for path in (ROOT / "data" / "vendors").glob("*/sources/*.yaml"):
        record = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(record, dict) and record.get("source_type"):
            recorded.add(str(record["source_type"]))
    assert recorded <= set(EXPECTED_LABELS)


def test_page_supports_no_source_type_outside_the_schema():
    index_html = (ROOT / "site/src/index.html").read_text(encoding="utf-8")
    page_types = set(re.findall(r'data-source-pack-field="([a-z0-9_]+)"', index_html))
    assert page_types <= schema_source_types()

    app_js = (ROOT / "site/src/app.js").read_text(encoding="utf-8")
    # The page must not define its own source-type label enum; it uses the
    # labels delivered by the compiled data/source-types.json.
    assert "SOURCE_TYPE_LABELS = sourceTypes.labels" in app_js.replace("\n", " ")
    # Result-pack alias targets stay inside the schema vocabulary (the pack's
    # own output keys are a separate stable machine contract).
    alias_block = app_js.split("const RESULT_PACK_RESOLVER_TYPES_BY_OUTPUT = {", 1)[1].split("};", 1)[0]
    alias_types = set(re.findall(r'"([a-z0-9_]+)"', alias_block))
    assert alias_types <= schema_source_types()


def test_no_schema_source_type_disappears_from_the_catalog_interface(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("openva_site_build_labels", ROOT / "site" / "build.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    compiled = module.build_compiled_catalog()
    assert set(compiled["source_types"]) == schema_source_types()
    assert compiled["source_type_labels"] == EXPECTED_LABELS
    assert set(compiled["source_type_counts"]) == schema_source_types()
    # Types with no records yet stay present with zero counts instead of
    # silently disappearing.
    assert all(count >= 0 for count in compiled["source_type_counts"].values())


def test_agent_exports_carry_the_label_dictionary_without_renaming_keys():
    text = (ROOT / "tools/openva/agent_export.py").read_text(encoding="utf-8")
    assert "source_type_labels()" in text
    assert '"source_type": source_record.get("source_type")' in text.replace("\n", " ") or (
        '"source_type"' in text
    )
