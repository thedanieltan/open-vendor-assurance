from __future__ import annotations

from pathlib import Path

import yaml

from tools.openva.discovery_mesh import CrawlLimits
from tools.openva.discovery_mesh_runner import (
    aggregate_shard_reports,
    run_source_shard,
    selected_vendor_paths,
    shard_for,
)
from tools.openva.source_verification import FetchResult


def write_vendor(root: Path, vendor_id: str, domain: str) -> None:
    path = root / "data" / "vendors" / vendor_id / "vendor.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "0.1.0",
                "vendor_id": vendor_id,
                "display_name": vendor_id.title(),
                "official_domains": [domain],
                "public_entrypoints": [f"https://{domain}"],
                "vendor_categories": ["developer_platform"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def result(url: str, body: str, status: int = 200) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        http_status=status,
        content_type="text/html; charset=utf-8",
        content_length=len(body.encode("utf-8")),
        etag=None,
        last_modified=None,
        body_sample=body.encode("utf-8"),
        error=None,
    )


def test_shard_assignment_is_stable_and_exhaustive(tmp_path: Path) -> None:
    for vendor_id in ("alpha", "beta", "gamma", "delta"):
        write_vendor(tmp_path, vendor_id, f"{vendor_id}.example")

    selected = []
    for index in range(4):
        selected.extend(path.parent.name for path in selected_vendor_paths(root=tmp_path, shard_index=index, shard_count=4))

    assert sorted(selected) == ["alpha", "beta", "delta", "gamma"]
    assert shard_for("alpha", 4) == shard_for("alpha", 4)


def test_source_shard_verifies_html_graph_candidates(tmp_path: Path) -> None:
    write_vendor(tmp_path, "alpha", "alpha.example")
    pages = {
        "https://alpha.example/": result(
            "https://alpha.example/",
            '<html><a href="/legal/data-processing-addendum">Data Processing Addendum</a></html>',
        ),
        "https://www.alpha.example/": result("https://www.alpha.example/", "", status=404),
        "https://alpha.example/legal/data-processing-addendum": result(
            "https://alpha.example/legal/data-processing-addendum",
            "<html><title>Data Processing Addendum</title><p>Controller processor personal data processing terms.</p></html>",
        ),
    }

    def factory(_vendor, _timeout):
        return lambda url: pages.get(url, result(url, "", status=404))

    report = run_source_shard(
        root=tmp_path,
        shard_index=0,
        shard_count=1,
        source_types=("dpa",),
        fetcher_factory=factory,
        limits=CrawlLimits(max_pages=50, max_total_requests=80),
        generated_at="2026-07-10T09:00:00Z",
    )

    assert report["summary"]["vendors_checked"] == 1
    assert report["summary"]["candidate_sources_written_or_reported"] == 1
    candidate = report["vendors"][0]["candidates"][0]
    assert candidate["source_type_candidate"] == "dpa"
    assert candidate["candidate_url"] == "https://alpha.example/legal/data-processing-addendum"
    assert candidate["evidence"]["http_status"] == 200


def test_aggregate_stages_candidates_without_writing_canonical_sources(tmp_path: Path) -> None:
    write_vendor(tmp_path, "alpha", "alpha.example")
    candidate = {
        "schema_version": "0.1.0",
        "candidate_source_id": "alpha-dpa-abc123",
        "vendor_id": "alpha",
        "source_type_candidate": "dpa",
        "candidate_url": "https://alpha.example/dpa",
        "requested_url": "https://alpha.example/dpa",
        "observed_final_url": "https://alpha.example/dpa",
        "canonical_candidate_url": "https://alpha.example/dpa",
        "candidate_status": "selected",
        "selection_run_id": "2026-07-10T09:00:00Z",
        "superseded_by_candidate_id": None,
        "evidence_digest": "sha256:test",
        "discovery_method": "html_link_graph",
        "confidence": "likely",
        "requires_review": True,
        "discovered_at": "2026-07-10T09:00:00Z",
        "discovered_by": "agent",
        "evidence": {
            "page_title": "Data Processing Addendum",
            "matched_terms": ["data processing"],
            "final_url": "https://alpha.example/dpa",
            "http_status": 200,
            "content_type": "text/html",
            "semantic_status": "strong",
            "verification_status": "verified",
            "soft_404_detected": False,
        },
        "notes": "Candidate only.",
        "not_advice": True,
    }
    shard_report = {
        "schema_version": "0.1.0",
        "generated_at": "2026-07-10T09:00:00Z",
        "report_type": "discovery_mesh_source_report",
        "summary": {},
        "vendors": [
            {
                "vendor_id": "alpha",
                "candidates": [candidate],
                "unavailable_sources": [],
                "observations": [],
                "discovery_events": [],
            }
        ],
        "source_frontier_reports": [],
        "vendor_identity_signals": [],
    }

    source_report, identity_report, manifest = aggregate_shard_reports(
        [shard_report],
        root=tmp_path,
        write_candidates=True,
        generated_at="2026-07-10T09:00:00Z",
    )

    candidate_path = tmp_path / "data" / "vendors" / "alpha" / "candidate_sources" / "alpha-dpa-abc123.yaml"
    canonical_path = tmp_path / "data" / "vendors" / "alpha" / "sources" / "alpha-dpa.yaml"
    assert candidate_path.exists()
    assert not canonical_path.exists()
    assert source_report["summary"]["candidate_sources_written_or_reported"] == 1
    assert identity_report["summary"]["candidate_count"] == 0
    assert manifest["candidate_paths"] == [
        "data/vendors/alpha/candidate_sources/alpha-dpa-abc123.yaml"
    ]
