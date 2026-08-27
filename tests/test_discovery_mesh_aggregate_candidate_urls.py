from __future__ import annotations

from tools.openva.discovery_mesh_runner import aggregate_shard_reports


def _report(*vendors: dict) -> dict:
    return {
        "source_frontier_reports": [],
        "vendor_identity_signals": [],
        "vendors": list(vendors),
    }


def test_aggregate_deduplicates_normalized_candidate_urls_across_vendors(tmp_path):
    report = _report(
        {
            "vendor_id": "alpha",
            "candidates": [
                {
                    "candidate_source_id": "alpha-shared",
                    "candidate_url": "https://shared.example/doc/",
                }
            ],
        },
        {
            "vendor_id": "beta",
            "candidates": [
                {
                    "candidate_source_id": "beta-shared",
                    "candidate_url": "https://shared.example/doc",
                }
            ],
        },
    )

    source_report, _, manifest = aggregate_shard_reports(
        [report],
        root=tmp_path,
        generated_at="2026-08-28T00:00:00Z",
    )

    candidates = [
        candidate
        for vendor in source_report["vendors"]
        for candidate in vendor.get("candidates", [])
    ]
    assert [candidate["candidate_source_id"] for candidate in candidates] == ["alpha-shared"]
    assert manifest["candidate_source_ids"] == ["alpha-shared"]
    assert manifest["candidate_count"] == 1


def test_aggregate_does_not_restage_an_existing_candidate_url(tmp_path):
    existing = tmp_path / "data/vendors/existing/candidate_sources/existing-source.yaml"
    existing.parent.mkdir(parents=True)
    existing.write_text(
        "candidate_source_id: existing-source\n"
        "vendor_id: existing\n"
        "candidate_url: https://shared.example/doc/\n",
        encoding="utf-8",
    )
    report = _report(
        {
            "vendor_id": "new-vendor",
            "candidates": [
                {
                    "candidate_source_id": "new-shared",
                    "candidate_url": "https://shared.example/doc",
                }
            ],
        }
    )

    source_report, _, manifest = aggregate_shard_reports(
        [report],
        root=tmp_path,
        generated_at="2026-08-28T00:00:00Z",
    )

    assert source_report["vendors"][0]["candidates"] == []
    assert manifest["candidate_source_ids"] == []
    assert manifest["candidate_count"] == 0
