from tools.openva.source_health import build_source_health_report

PUBLIC_ACCESS_CLASSES = {
    "public_web",
    "public_pdf",
    "public_doc_portal",
    "public_landing_gated_docs",
}


def test_source_health_report_is_inventory_only_and_non_advisory():
    report = build_source_health_report()

    assert report["report_type"] == "source_health_inventory"
    assert report["posture"] == {
        "network_fetch_performed": False,
        "writes_repository_state": False,
        "opens_pull_requests": False,
        "public_sources_only": True,
        "non_advisory": True,
    }
    assert report["summary"]["vendor_count"] >= 0
    assert report["summary"]["source_count"] >= 0
    assert isinstance(report["sources"], list)


def test_source_health_report_preserves_public_metadata_contract():
    report = build_source_health_report()

    for source in report["sources"]:
        assert source["source_url"].startswith(("http://", "https://"))
        assert source["access_class"] in PUBLIC_ACCESS_CLASSES
        assert source["rights_class"] == "metadata_only"


def test_source_health_report_does_not_flag_public_pdfs_by_format_only(tmp_path):
    source_dir = tmp_path / "data" / "vendors" / "example" / "sources"
    artifact_dir = tmp_path / "data" / "vendors" / "example" / "artifacts"
    source_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    (source_dir / "example-dpa.yaml").write_text(
        """
schema_version: 0.1.0
source_id: example-dpa
vendor_id: example
source_type: dpa
title_native: Example DPA
source_url: https://example.com/dpa.pdf
source_language: en
access_class: public_pdf
rights_class: metadata_only
provenance:
  publisher: vendor
  collected_at: '2026-05-18T00:00:00Z'
  observer: human
  confidence: medium
not_advice: true
""".lstrip(),
        encoding="utf-8",
    )

    report = build_source_health_report(root=tmp_path)

    assert report["summary"]["sources_with_issues"] == 0
    assert report["breakdowns"]["issues"] == {}
