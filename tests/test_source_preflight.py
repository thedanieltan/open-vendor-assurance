from __future__ import annotations

import json
from pathlib import Path

import yaml

from tools.openva.source_preflight import check_changed_sources, main


def write_source(root: Path, path: str, *, source_url: str = "https://vendor.example/security") -> Path:
    full_path = root / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(
        yaml.safe_dump(
            {
                "vendor_id": "vendor-a",
                "source_id": "vendor-a-security",
                "source_type": "security_page",
                "source_url": source_url,
                "source_authority_class": "vendor_published",
                "access_class": "public_web",
                "rights_class": "public_reference",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return full_path


def verifier(status: str):
    def _verify(source: dict, path: Path) -> dict:
        return {
            "path": str(path),
            "vendor_id": source["vendor_id"],
            "source_id": source["source_id"],
            "source_type": source["source_type"],
            "source_url": source["source_url"],
            "final_url": source["source_url"] if status != "redirected" else source["source_url"] + "/current",
            "http_status": 200 if status in {"ok", "redirected", "possible_mismatch"} else 404,
            "verification_status": status,
            "requires_review": status not in {"ok", "redirected"},
        }

    return _verify


def test_no_changed_source_records_passes_with_clear_message(tmp_path: Path):
    report = check_changed_sources(
        ["indexes/sources.json", "openva-pack.json"],
        root=tmp_path,
        verifier=verifier("ok"),
        generated_at="2026-05-24T13:30:00Z",
    )

    assert report["changed_source_count"] == 0
    assert report["checked_source_count"] == 0
    assert report["failed_count"] == 0
    assert report["skipped_count"] == 2
    assert report["message"] == "No changed source records requiring source preflight."
    assert report["posture"]["network_fetch_performed"] is False


def test_changed_source_with_ok_passes(tmp_path: Path):
    path = "data/vendors/vendor-a/sources/vendor-a-security.yaml"
    write_source(tmp_path, path)

    report = check_changed_sources([path], root=tmp_path, verifier=verifier("ok"))

    assert report["changed_source_count"] == 1
    assert report["checked_source_count"] == 1
    assert report["passed_count"] == 1
    assert report["failed_count"] == 0
    assert report["checked_sources"][0]["verification_status"] == "ok"
    assert report["posture"]["network_fetch_performed"] is True


def test_changed_source_with_redirected_passes(tmp_path: Path):
    path = "data/vendors/vendor-a/sources/vendor-a-security.yaml"
    write_source(tmp_path, path)

    report = check_changed_sources([path], root=tmp_path, verifier=verifier("redirected"))

    assert report["passed_count"] == 1
    assert report["failed_count"] == 0
    assert report["checked_sources"][0]["verification_status"] == "redirected"


def test_changed_source_with_not_found_fails(tmp_path: Path):
    path = "data/vendors/vendor-a/sources/vendor-a-security.yaml"
    write_source(tmp_path, path)

    report = check_changed_sources([path], root=tmp_path, verifier=verifier("not_found"))

    assert report["passed_count"] == 0
    assert report["failed_count"] == 1
    assert report["failures"][0]["reason"] == "source_preflight_failed:not_found"


def test_changed_source_with_possible_mismatch_fails(tmp_path: Path):
    path = "data/vendors/vendor-a/sources/vendor-a-security.yaml"
    write_source(tmp_path, path)

    report = check_changed_sources([path], root=tmp_path, verifier=verifier("possible_mismatch"))

    assert report["failed_count"] == 1
    assert report["failures"][0]["reason"] == "source_preflight_failed:possible_mismatch"


def test_changed_source_with_bot_protected_fails(tmp_path: Path):
    path = "data/vendors/vendor-a/sources/vendor-a-security.yaml"
    write_source(tmp_path, path)

    report = check_changed_sources([path], root=tmp_path, verifier=verifier("bot_protected"))

    assert report["failed_count"] == 1
    assert report["failures"][0]["reason"] == "source_preflight_failed:bot_protected"


def test_unknown_verification_status_fails(tmp_path: Path):
    path = "data/vendors/vendor-a/sources/vendor-a-security.yaml"
    write_source(tmp_path, path)

    report = check_changed_sources([path], root=tmp_path, verifier=verifier("future_status"))

    assert report["failed_count"] == 1
    assert report["failures"][0]["reason"] == "source_preflight_failed:unknown_status:future_status"


def test_only_changed_vendor_source_yaml_files_are_checked(tmp_path: Path):
    path = "data/vendors/vendor-a/sources/vendor-a-security.yaml"
    write_source(tmp_path, path)
    calls: list[str] = []

    def recording_verifier(source: dict, source_path: Path) -> dict:
        calls.append(str(source_path.relative_to(tmp_path)).replace("\\", "/"))
        return verifier("ok")(source, source_path)

    report = check_changed_sources(
        [
            path,
            "data/vendors/vendor-a/vendor.yaml",
            "data/vendors/vendor-a/unavailable_sources/vendor-a-security.yaml",
            "indexes/sources.json",
        ],
        root=tmp_path,
        verifier=recording_verifier,
    )

    assert calls == [path]
    assert report["changed_source_count"] == 1
    assert report["checked_source_count"] == 1
    assert report["skipped_count"] == 3


def test_output_contains_no_self_certifying_fields(tmp_path: Path):
    path = "data/vendors/vendor-a/sources/vendor-a-security.yaml"
    write_source(tmp_path, path)

    report = check_changed_sources([path], root=tmp_path, verifier=verifier("ok"))
    text = json.dumps(report, sort_keys=True)

    assert "eligible" not in text
    assert "eligible_for_automerge" not in text
    assert "tool_recommendation" not in text


def test_cli_writes_report_and_returns_failure_for_failed_source(tmp_path: Path, monkeypatch):
    path = "data/vendors/vendor-a/sources/vendor-a-security.yaml"
    write_source(tmp_path, path)
    paths_file = tmp_path / "changed-files.txt"
    output = tmp_path / "source-preflight-report.json"
    paths_file.write_text(path + "\n", encoding="utf-8")

    monkeypatch.setattr(
        "tools.openva.source_preflight.default_verifier",
        verifier("not_found"),
    )

    assert main([
        "check-changed-sources",
        "--paths-file",
        str(paths_file),
        "--output",
        str(output),
        "--root",
        str(tmp_path),
    ]) == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["failed_count"] == 1
