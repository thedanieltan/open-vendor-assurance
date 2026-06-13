"""WP36 missing_vendor -> candidate bridge tests."""

from __future__ import annotations

from pathlib import Path

import yaml

from tools.openva import missing_vendor_bridge as bridge


def write_vendor(root: Path, vendor_id: str, *, domains: list[str], name: str) -> None:
    vdir = root / "data" / "vendors" / vendor_id
    vdir.mkdir(parents=True)
    (vdir / "vendor.yaml").write_text(
        yaml.safe_dump({"vendor_id": vendor_id, "display_name": name, "official_domains": domains}),
        encoding="utf-8",
    )


TARGETS = {
    "categories": {
        "cloud": {
            "weight": 5,
            "taxonomy_tags": ["cloud_infrastructure"],
            "priority_vendors": [
                {"vendor_id": "ovhcloud", "name": "OVHcloud", "domain": "ovhcloud.com", "country": "FR"},
                {"vendor_id": "scaleway", "name": "Scaleway"},  # no domain -> skip
                {"vendor_id": "existingco", "name": "Existing Co", "domain": "existing.com", "country": "US"},
            ],
        }
    }
}

COVERAGE = {
    "growth_queue": [
        {"queue_class": "missing_vendor", "vendor_id": "ovhcloud", "category": "cloud"},
        {"queue_class": "missing_vendor", "vendor_id": "scaleway", "category": "cloud"},
        {"queue_class": "missing_vendor", "vendor_id": "existingco", "category": "cloud"},
        {"queue_class": "missing_vendor", "vendor_id": "notwishlisted", "category": "cloud"},
        {"queue_class": "missing_source_type", "vendor_id": "ignored"},
    ]
}


def test_bridge_materializes_genuinely_missing_wishlist_vendor(tmp_path):
    (tmp_path / "data" / "vendors").mkdir(parents=True)
    # existing.com is already in the catalog -> existingco must collide.
    write_vendor(tmp_path, "someco", domains=["existing.com"], name="Some Co")

    report = bridge.build_bridge_report(COVERAGE, TARGETS, root=tmp_path, generated_at="2026-06-13T00:00:00Z")

    assert report["report_type"] == "vendor_candidate_discovery_report"
    candidates = {c["candidate_vendor_id"]: c for c in report["vendor_candidates"]}
    assert set(candidates) == {"ovhcloud"}
    ovh = candidates["ovhcloud"]
    assert ovh["official_domain_candidate"] == "ovhcloud.com"
    assert ovh["headquarters_country_candidate"] == "FR"
    assert ovh["vendor_category_candidates"] == ["cloud_infrastructure"]
    assert ovh["requires_review"] is True and ovh["writes_canonical_vendors"] is False

    skipped = {s["vendor_id"]: s for s in report["bridge_skipped"]}
    assert skipped["scaleway"]["reason"] == "wishlist_missing_domain_or_country"
    assert skipped["existingco"]["reason"] == "already_in_catalog"
    assert "official_domain" in skipped["existingco"]["collisions"]
    assert skipped["notwishlisted"]["reason"] == "not_in_wishlist"
    assert report["summary"]["candidate_vendor_count"] == 1


def test_bridge_detects_vendor_id_and_name_collisions(tmp_path):
    (tmp_path / "data" / "vendors").mkdir(parents=True)
    write_vendor(tmp_path, "ovhcloud", domains=["other.com"], name="OVHcloud")  # id + name collide
    report = bridge.build_bridge_report(COVERAGE, TARGETS, root=tmp_path, generated_at="2026-06-13T00:00:00Z")
    skipped = {s["vendor_id"]: s for s in report["bridge_skipped"]}
    assert skipped["ovhcloud"]["reason"] == "already_in_catalog"
    assert "vendor_id" in skipped["ovhcloud"]["collisions"]
    assert "name_or_alias" in skipped["ovhcloud"]["collisions"]


def test_bridge_detects_previous_domain_collision(tmp_path):
    (tmp_path / "data" / "vendors").mkdir(parents=True)
    vdir = tmp_path / "data" / "vendors" / "renamed"
    vdir.mkdir(parents=True)
    (vdir / "vendor.yaml").write_text(
        yaml.safe_dump({
            "vendor_id": "renamed",
            "display_name": "Renamed Co",
            "official_domains": ["new.com"],
            "previous_domains": ["ovhcloud.com"],
        }),
        encoding="utf-8",
    )
    report = bridge.build_bridge_report(COVERAGE, TARGETS, root=tmp_path, generated_at="2026-06-13T00:00:00Z")
    skipped = {s["vendor_id"]: s for s in report["bridge_skipped"]}
    assert skipped["ovhcloud"]["reason"] == "already_in_catalog"
    assert "official_domain" in skipped["ovhcloud"]["collisions"]
