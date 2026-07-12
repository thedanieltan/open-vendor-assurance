import json
from pathlib import Path

import pytest

from tools.openva.catalog_growth_discovery_queue import (
    MODE_CAPABILITIES,
    SITEMAP_DISCOVERY_MODE,
    _normalize_reason,
    expected_posture,
    validate_queue,
)


def test_rejection_reason_codes_cannot_leak_raw_text():
    # Bounded codes pass through; the ParseError tail is dropped; anything with
    # whitespace/markup/free text (a page or robots snippet) maps to a generic code.
    assert _normalize_reason("off_authority_sitemap") == "off_authority_sitemap"
    assert _normalize_reason("sitemap_http_503") == "sitemap_http_503"
    assert _normalize_reason("discovery_suppressed:robots_transport_error") == "discovery_suppressed:robots_transport_error"
    assert _normalize_reason("malformed_sitemap_xml:not well-formed: line 1, column 5") == "malformed_sitemap_xml"
    assert _normalize_reason("<title>Secret internal page</title>") == "rejected_other"
    assert _normalize_reason("User-agent: * Disallow: /secret raw robots body") == "rejected_other"
    assert _normalize_reason("x" * 200) == "rejected_other"


QUEUE = Path("maintenance/queues/catalog-growth-discovery.json")


def _write(tmp_path, queue):
    path = tmp_path / "catalog-growth-discovery.json"
    path.write_text(json.dumps(queue), encoding="utf-8")
    return path


def test_catalog_growth_discovery_queue_is_taxonomy_driven_and_bounded():
    summary = validate_queue(QUEUE)

    assert summary["queue_type"] == "catalog_growth_discovery_queue"
    assert summary["cohort_count"] >= 10
    assert summary["queued_cohort_count"] >= 10
    assert summary["target_vendor_candidates"] >= 200
    assert "cloud_platforms" in summary["coverage_lane_counts"]
    assert "security_identity" in summary["coverage_lane_counts"]
    assert "regional_apac" in summary["coverage_lane_counts"]
    assert set(summary["source_types"]) == {
        "dpa",
        "subprocessors_list",
        "privacy_notice",
        "trust_center",
        "security_page",
        "compliance_page",
        "certification_reference",
        "terms_of_service",
        "kyc_statement",
        "aml_statement",
        "ai_terms",
        "government_request_policy",
        "transparency_report",
        "status_page",
        "other_public_source",
    }


def test_catalog_growth_discovery_queue_posture_reflects_network_modes_but_never_writes():
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))

    assert queue["non_advisory"] is True
    # The committed queue enables network-fetching modes, so the posture must
    # honestly declare network_fetch_performed; the write/create invariants stay
    # false because no discovery mode may mutate canonical/repository state.
    assert queue["posture"] == {
        "network_fetch_performed": True,
        "writes_repository_state": False,
        "writes_canonical_sources": False,
        "creates_candidate_sources": False,
    }
    assert queue["posture"] == expected_posture(queue["discovery_modes"])
    for key in ("writes_repository_state", "writes_canonical_sources", "creates_candidate_sources"):
        assert queue["posture"][key] is False
    assert queue["limits"]["max_vendors_per_discovery_run"] <= 25
    assert queue["limits"]["max_reviewed_actions_per_plan"] <= 50


def test_network_fetching_mode_cannot_be_enabled_under_no_network_posture(tmp_path):
    # The exact defect the contract closes: a network-fetching mode declared with
    # a no-network posture must be rejected.
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    assert MODE_CAPABILITIES[SITEMAP_DISCOVERY_MODE]["network_fetch_performed"] is True
    queue["posture"]["network_fetch_performed"] = False
    with pytest.raises(ValueError, match="network_fetch_performed must be True"):
        validate_queue(_write(tmp_path, queue))


def test_mode_capabilities_must_match_authoritative_registry(tmp_path):
    # An artifact cannot under-declare a network mode as non-fetching to dodge
    # the posture rule.
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    queue["mode_capabilities"][SITEMAP_DISCOVERY_MODE]["network_fetch_performed"] = False
    with pytest.raises(ValueError, match="network_fetch_performed must be True"):
        validate_queue(_write(tmp_path, queue))


def test_mode_capabilities_must_cover_exactly_enabled_modes(tmp_path):
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    del queue["mode_capabilities"][SITEMAP_DISCOVERY_MODE]
    with pytest.raises(ValueError, match="exactly the enabled discovery_modes"):
        validate_queue(_write(tmp_path, queue))


def test_no_mode_may_declare_a_write_or_create_capability(tmp_path):
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    # Even if an artifact tries to claim a write capability, the registry forbids
    # it (the mode's authoritative capability is false), so validation fails.
    queue["mode_capabilities"][SITEMAP_DISCOVERY_MODE]["writes_canonical_sources"] = True
    queue["posture"]["writes_canonical_sources"] = True
    with pytest.raises(ValueError, match="writes_canonical_sources must be False"):
        validate_queue(_write(tmp_path, queue))


def test_mode_capabilities_is_optional_but_posture_is_still_enforced(tmp_path):
    # A queue that omits the optional mode_capabilities declaration still
    # validates, and posture is still enforced against the authoritative code
    # registry: a network mode without a network posture is rejected even with
    # no declaration to check.
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    del queue["mode_capabilities"]
    validate_queue(_write(tmp_path, queue))  # ok: posture matches the union

    queue["posture"]["network_fetch_performed"] = False
    with pytest.raises(ValueError, match="network_fetch_performed must be True"):
        validate_queue(_write(tmp_path, queue))


def test_overclaimed_network_posture_without_a_network_mode_is_rejected(tmp_path):
    # Posture is a derived fact, not a free assertion: no network mode => the
    # posture must say network_fetch_performed false.
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    queue["discovery_modes"] = ["seed_file_vendor_discovery"]
    queue["mode_capabilities"] = {"seed_file_vendor_discovery": dict(MODE_CAPABILITIES["seed_file_vendor_discovery"])}
    queue["source_types"] = ["dpa"]
    # posture still claims network true (carried over) -> over-claim rejected.
    with pytest.raises(ValueError, match="network_fetch_performed must be False"):
        validate_queue(_write(tmp_path, queue))


def test_catalog_growth_discovery_queue_rejects_unknown_taxonomy_lane(tmp_path):
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    queue["cohorts"][0]["coverage_lane"] = "unknown_lane"
    bad_queue = tmp_path / "catalog-growth-discovery.json"
    bad_queue.write_text(json.dumps(queue), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown coverage lane"):
        validate_queue(bad_queue)


def test_catalog_growth_discovery_queue_rejects_unknown_source_type(tmp_path):
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    queue["source_types"].append("unknown_source_type")
    bad_queue = tmp_path / "catalog-growth-discovery.json"
    bad_queue.write_text(json.dumps(queue), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown source type"):
        validate_queue(bad_queue)
