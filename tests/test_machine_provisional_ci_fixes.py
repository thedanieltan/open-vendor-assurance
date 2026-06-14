"""WP40 follow-up: live-cycle CI fixes surfaced by the first real machine-provisional PR.

1. catalog-pr-guard must allow the append-only machine-decisions ledger path.
2. full_baseline_readiness must exempt machine_provisional sources (observed
   between materialization and promotion) from the active-catalog baseline.
"""

from __future__ import annotations

from datetime import UTC, datetime

import yaml

from tools.openva import catalog_guard
from tools.openva import release_gates


def test_machine_decisions_path_is_allowed_in_catalog_pr():
    assert catalog_guard.is_allowed_catalog_path("maintenance/machine-decisions/2026-06.ndjson")
    # a real machine-provisional PR file set must pass the guard
    paths = [
        "data/vendors/bitwarden/vendor.yaml",
        "data/vendors/bitwarden/sources/bitwarden-privacy-notice.yaml",
        "maintenance/machine-decisions/2026-06.ndjson",
        "indexes/vendors.json",
        "dist/vendors/bitwarden.json",
    ]
    assert catalog_guard.validate_catalog_pr(paths) == []


def test_non_ndjson_machine_decisions_path_still_rejected():
    # only the append-only ndjson ledger is allowed, not arbitrary files
    assert not catalog_guard.is_allowed_catalog_path("maintenance/machine-decisions/notes.txt")


def _seed_catalog(root, *, status):
    vdir = root / "data" / "vendors" / "acme"
    (vdir / "sources").mkdir(parents=True)
    (vdir / "vendor.yaml").write_text(
        yaml.safe_dump({"vendor_id": "acme", "catalog_status": status}), encoding="utf-8"
    )
    (vdir / "sources" / "acme-privacy.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "0.1.0", "source_id": "acme-privacy", "vendor_id": "acme",
            "source_type": "privacy_notice", "source_url": "https://acme.example/privacy",
            "source_authority_class": "vendor_published", "access_class": "public_web",
            "rights_class": "metadata_only",
        }),
        encoding="utf-8",
    )
    ledger = root / "maintenance" / "source-observations" / "events"
    ledger.mkdir(parents=True)
    return ledger


def _baseline_gate(root, ledger):
    ctx = release_gates.GateContext(
        root=root, ledger_dir=ledger, config={"freshness": {"require_full_baseline": True}},
        profile="pr", now=datetime(2026, 6, 14, tzinfo=UTC), commit_sha="deadbeef",
    )
    freshness = release_gates.compute_freshness(ctx)
    return release_gates.gate_full_baseline(ctx, freshness), freshness


def test_provisional_vendor_ids_detected(tmp_path):
    _seed_catalog(tmp_path, status="machine_provisional")
    assert release_gates.machine_provisional_vendor_ids(tmp_path) == {"acme"}


def test_baseline_gate_exempts_unobserved_provisional_source(tmp_path):
    ledger = _seed_catalog(tmp_path, status="machine_provisional")
    result, freshness = _baseline_gate(tmp_path, ledger)
    # the unobserved source belongs to a machine_provisional vendor -> exempt -> pass
    assert "acme-privacy" in freshness["provisional_source_ids"]
    assert result.status == release_gates.STATUS_PASS


def test_baseline_gate_still_fails_for_unobserved_active_source(tmp_path):
    ledger = _seed_catalog(tmp_path, status="active")
    result, _ = _baseline_gate(tmp_path, ledger)
    # an active vendor's unobserved source still blocks the baseline gate
    assert result.status == release_gates.STATUS_FAIL
    assert "acme-privacy" in " ".join(result.details)
