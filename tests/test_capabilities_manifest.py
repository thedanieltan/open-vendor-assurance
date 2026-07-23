"""WP-OPENVA-CAPABILITY-CONTRACT conformance + fail-closed freshness tests."""

from __future__ import annotations

import copy

from tools.openva import capabilities


def test_manifest_consistent_with_all_locked_surfaces():
    # The committed manifest must agree with controlled-vocabulary, schema enum,
    # SOURCE_TYPE_REGISTRY, browser arrays, RESULT_PACK_VERSION, and the generated artifact.
    assert capabilities.check() == []


def test_generated_artifact_is_committed_and_fresh():
    manifest = capabilities.load_manifest()
    expected = capabilities.render_generated_js(manifest)
    assert capabilities.GENERATED_JS_PATH.exists(), "generated artifact must be committed"
    assert capabilities.GENERATED_JS_PATH.read_text(encoding="utf-8") == expected


def test_generation_is_deterministic():
    manifest = capabilities.load_manifest()
    assert capabilities.render_generated_js(manifest) == capabilities.render_generated_js(manifest)


def test_manifest_source_types_match_schema_and_vocabulary_ordered():
    manifest = capabilities.load_manifest()
    ids = capabilities.source_type_ids(manifest)
    # 15 canonical types, order significant, no duplicates.
    assert len(ids) == len(set(ids))
    assert ids[0] == "dpa" and ids[-1] == "other_public_source"


def test_availability_sets_are_subsets_of_source_types():
    manifest = capabilities.load_manifest()
    ids = set(capabilities.source_type_ids(manifest))
    for key in ("discovery_supported", "browser_default_selected", "live_resolver_supported"):
        assert set(capabilities.availability(manifest, key)) <= ids, key


# --- fail-closed: prove drift is DETECTED, not silently accepted ------------- #
def test_check_fails_closed_when_source_type_dropped():
    manifest = copy.deepcopy(capabilities.load_manifest())
    manifest["source_types"] = manifest["source_types"][:-1]  # drop one type
    problems = capabilities.check(manifest)
    assert problems, "dropping a source type must be caught by the consistency check"


def test_check_fails_closed_when_result_pack_version_drifts():
    manifest = copy.deepcopy(capabilities.load_manifest())
    manifest["contracts"]["result_pack_version"] = "9.9.9"
    problems = capabilities.check(manifest)
    assert any("RESULT_PACK_VERSION" in p for p in problems)


def test_check_fails_closed_when_discovery_supported_drifts():
    manifest = copy.deepcopy(capabilities.load_manifest())
    manifest["availability"]["discovery_supported"].append("terms_of_service")
    problems = capabilities.check(manifest)
    assert any("discovery_supported" in p for p in problems)


def test_check_fails_closed_when_generated_artifact_stale():
    manifest = copy.deepcopy(capabilities.load_manifest())
    manifest["manifest_version"] = "0.0.0-stale"  # committed artifact no longer matches
    problems = capabilities.check(manifest)
    assert any("stale" in p for p in problems)
