from __future__ import annotations

import json
from pathlib import Path

import yaml

from tools.openva.source_repair_collision_check import build_collision_report, build_markdown_summary, main


def write_source(
    catalog_root: Path,
    *,
    vendor_id: str = "vendor-a",
    source_id: str = "vendor-a-dpa",
    source_type: str = "dpa",
    source_url: str = "https://vendor-a.example/old-dpa",
) -> Path:
    path = catalog_root / vendor_id / "sources" / f"{source_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "0.1.0",
                "vendor_id": vendor_id,
                "source_id": source_id,
                "source_type": source_type,
                "source_url": source_url,
                "review_state": "auto_validated",
                "catalog_tier": "machine_validated",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def validation_row(**updates):
    row = {
        "vendor_id": "vendor-a",
        "source_id": "vendor-a-dpa",
        "source_type": "dpa",
        "original_source_url": "https://vendor-a.example/old-dpa",
        "replacement_source_url": "https://vendor-a.example/new-dpa",
        "replacement_verification_status": "ok",
        "replacement_http_status": 200,
        "replacement_semantic_status": "strong",
        "replacement_authority_status": "vendor_controlled",
        "replacement_access_status": "public",
        "replacement_url_safety_status": "passed",
        "reasons": [],
    }
    row.update(updates)
    return row


def validation_report(rows):
    return {
        "schema_version": "0.1.0",
        "generated_at": "2026-05-26T00:00:00Z",
        "report_type": "p0_source_repair_plan_validation",
        "approved": rows,
        "rejected": [],
        "unmatched": [],
        "summary": {
            "approved_count": len(rows),
            "rejected_count": 0,
            "unmatched_count": 0,
        },
    }


def check(catalog_root: Path, rows: list[dict]):
    return build_collision_report(
        validation_report(rows),
        catalog_root=catalog_root,
        source_validation_report="maintenance/reviewed/validation.json",
    )


def collision_types(report):
    return [item["collision_type"] for item in report["collisions"]]


def test_no_collisions_exits_success_and_reports_zero(tmp_path):
    catalog_root = tmp_path / "data" / "vendors"
    row = validation_row()
    write_source(catalog_root)
    validation_path = tmp_path / "validation.json"
    output_path = tmp_path / "collision.json"
    summary_path = tmp_path / "collision.md"
    validation_path.write_text(json.dumps(validation_report([row])), encoding="utf-8")

    status = main(
        [
            "check",
            "--validation",
            str(validation_path),
            "--catalog-root",
            str(catalog_root),
            "--output",
            str(output_path),
            "--summary-output",
            str(summary_path),
        ]
    )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert status == 0
    assert report["summary"]["collision_count"] == 0
    assert report["summary"]["blocking_collision_count"] == 0
    assert summary_path.read_text(encoding="utf-8").startswith("# P0 Source Repair Collision Summary")


def test_two_rows_same_vendor_same_replacement_url_are_blocking_and_ordered(tmp_path):
    catalog_root = tmp_path / "data" / "vendors"
    write_source(catalog_root, source_id="vendor-a-security", source_type="security_page", source_url="https://vendor-a.example/old-security")
    write_source(catalog_root, source_id="vendor-a-dpa", source_type="dpa", source_url="https://vendor-a.example/old-dpa")
    rows = [
        validation_row(
            source_id="vendor-a-security",
            source_type="security_page",
            original_source_url="https://vendor-a.example/old-security",
            replacement_source_url="https://Vendor-A.example/trust/",
        ),
        validation_row(replacement_source_url="https://vendor-a.example/trust"),
    ]

    report = check(catalog_root, rows)

    duplicate = next(item for item in report["collisions"] if item["collision_type"] == "intra_batch_duplicate_replacement_url")
    assert duplicate["severity"] == "blocking"
    assert duplicate["normalized_url"] == "https://vendor-a.example/trust"
    assert [source["source_id"] for source in duplicate["affected_sources"]] == [
        "vendor-a-dpa",
        "vendor-a-security",
    ]


def test_replacement_url_already_exists_in_another_same_vendor_source_is_blocking(tmp_path):
    catalog_root = tmp_path / "data" / "vendors"
    write_source(catalog_root)
    write_source(
        catalog_root,
        source_id="vendor-a-compliance",
        source_type="compliance_page",
        source_url="https://vendor-a.example/trust/",
    )

    report = check(catalog_root, [validation_row(replacement_source_url="https://vendor-a.example/trust")])

    assert "existing_catalog_duplicate_source_url" in collision_types(report)
    assert "post_application_duplicate_source_url" in collision_types(report)
    assert report["summary"]["blocking_collision_count"] == 2


def test_batch_006_style_duplicate_collisions_are_blocking(tmp_path):
    catalog_root = tmp_path / "data" / "vendors"
    write_source(catalog_root, vendor_id="miro", source_id="miro-compliance", source_type="compliance_page", source_url="https://miro.com/security/compliance/")
    write_source(catalog_root, vendor_id="miro", source_id="miro-security", source_type="security_page", source_url="https://miro.com/security/")
    write_source(catalog_root, vendor_id="mistral-ai", source_id="mistral-ai-compliance", source_type="compliance_page", source_url="https://mistral.ai/trust/")
    write_source(catalog_root, vendor_id="mistral-ai", source_id="mistral-ai-security", source_type="security_page", source_url="https://mistral.ai/security/")
    write_source(catalog_root, vendor_id="retool", source_id="retool-compliance", source_type="compliance_page", source_url="https://trust.retool.com/")
    write_source(catalog_root, vendor_id="retool", source_id="retool-security", source_type="security_page", source_url="https://retool.com/security")
    rows = [
        validation_row(
            vendor_id="miro",
            source_id="miro-compliance",
            source_type="compliance_page",
            original_source_url="https://miro.com/security/compliance/",
            replacement_source_url="https://trust.miro.com/",
        ),
        validation_row(
            vendor_id="miro",
            source_id="miro-security",
            source_type="security_page",
            original_source_url="https://miro.com/security/",
            replacement_source_url="https://trust.miro.com/",
        ),
        validation_row(
            vendor_id="mistral-ai",
            source_id="mistral-ai-compliance",
            source_type="compliance_page",
            original_source_url="https://mistral.ai/trust/",
            replacement_source_url="https://trust.mistral.ai/",
        ),
        validation_row(
            vendor_id="mistral-ai",
            source_id="mistral-ai-security",
            source_type="security_page",
            original_source_url="https://mistral.ai/security/",
            replacement_source_url="https://trust.mistral.ai/",
        ),
        validation_row(
            vendor_id="retool",
            source_id="retool-security",
            source_type="security_page",
            original_source_url="https://retool.com/security",
            replacement_source_url="https://trust.retool.com/",
        ),
    ]

    report = check(catalog_root, rows)

    types = collision_types(report)
    assert types.count("intra_batch_duplicate_replacement_url") == 2
    assert "existing_catalog_duplicate_source_url" in types
    assert "post_application_duplicate_source_url" in types
    assert report["summary"]["blocking_collision_count"] >= 3


def test_replacement_url_same_as_original_after_normalization_is_blocking(tmp_path):
    catalog_root = tmp_path / "data" / "vendors"
    write_source(catalog_root, source_url="https://Vendor-A.example/old-dpa/")

    report = check(
        catalog_root,
        [
            validation_row(
                original_source_url="https://Vendor-A.example/old-dpa/",
                replacement_source_url="https://vendor-a.example/old-dpa",
            )
        ],
    )

    assert collision_types(report) == ["replacement_url_same_as_original"]
    assert report["collisions"][0]["reason"] == "replacement_source_url_normalizes_to_original_source_url"


def test_same_replacement_url_across_different_vendors_is_allowed(tmp_path):
    catalog_root = tmp_path / "data" / "vendors"
    write_source(catalog_root, vendor_id="vendor-a", source_id="dpa-a", source_url="https://a.example/old")
    write_source(catalog_root, vendor_id="vendor-b", source_id="dpa-b", source_url="https://b.example/old")
    rows = [
        validation_row(
            vendor_id="vendor-a",
            source_id="dpa-a",
            original_source_url="https://a.example/old",
            replacement_source_url="https://shared.example/legal",
        ),
        validation_row(
            vendor_id="vendor-b",
            source_id="dpa-b",
            original_source_url="https://b.example/old",
            replacement_source_url="https://shared.example/legal",
        ),
    ]

    report = check(catalog_root, rows)

    assert report["summary"]["blocking_collision_count"] == 0
    assert report["collisions"] == []


def test_final_url_collision_is_warning_when_replacement_source_urls_differ(tmp_path):
    catalog_root = tmp_path / "data" / "vendors"
    write_source(catalog_root, source_id="vendor-a-dpa", source_url="https://vendor-a.example/old-dpa")
    write_source(catalog_root, source_id="vendor-a-security", source_type="security_page", source_url="https://vendor-a.example/old-security")
    rows = [
        validation_row(
            source_id="vendor-a-security",
            source_type="security_page",
            original_source_url="https://vendor-a.example/old-security",
            replacement_source_url="https://vendor-a.example/security",
            replacement_final_url="https://vendor-a.example/trust",
        ),
        validation_row(
            replacement_source_url="https://vendor-a.example/compliance",
            replacement_final_url="https://vendor-a.example/trust/",
        ),
    ]

    report = check(catalog_root, rows)

    assert report["summary"]["blocking_collision_count"] == 0
    assert [item["collision_type"] for item in report["warnings"]] == ["final_url_collision"]
    assert report["summary"]["warning_count"] == 1


def test_output_ordering_is_deterministic(tmp_path):
    catalog_root = tmp_path / "data" / "vendors"
    write_source(catalog_root, source_id="b", source_url="https://vendor-a.example/b-old")
    write_source(catalog_root, source_id="a", source_url="https://vendor-a.example/a-old")
    rows = [
        validation_row(source_id="b", original_source_url="https://vendor-a.example/b-old", replacement_source_url="https://vendor-a.example/shared"),
        validation_row(source_id="a", original_source_url="https://vendor-a.example/a-old", replacement_source_url="https://vendor-a.example/shared"),
    ]

    report = check(catalog_root, rows)

    duplicate = next(item for item in report["collisions"] if item["collision_type"] == "intra_batch_duplicate_replacement_url")
    assert [source["source_id"] for source in duplicate["affected_sources"]] == ["a", "b"]


def test_markdown_summary_includes_blocking_collision_details(tmp_path):
    catalog_root = tmp_path / "data" / "vendors"
    write_source(catalog_root)
    report = check(catalog_root, [validation_row(replacement_source_url="https://vendor-a.example/old-dpa/")])

    markdown = build_markdown_summary(report)

    assert "## Blocking Collisions" in markdown
    assert "`replacement_url_same_as_original`" in markdown
    assert "`vendor-a/vendor-a-dpa`" in markdown


def test_cli_does_not_mutate_catalog(tmp_path):
    catalog_root = tmp_path / "data" / "vendors"
    source_path = write_source(catalog_root)
    before = source_path.read_text(encoding="utf-8")
    validation_path = tmp_path / "validation.json"
    validation_path.write_text(json.dumps(validation_report([validation_row()])), encoding="utf-8")

    status = main(
        [
            "check",
            "--validation",
            str(validation_path),
            "--catalog-root",
            str(catalog_root),
            "--output",
            str(tmp_path / "collision.json"),
            "--summary-output",
            str(tmp_path / "collision.md"),
        ]
    )

    assert status == 0
    assert source_path.read_text(encoding="utf-8") == before
