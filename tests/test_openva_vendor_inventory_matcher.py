import csv
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("adapters/python/openva_pack_reader").resolve()))
sys.path.insert(0, str(Path("adapters/python/openva_vendor_inventory_matcher").resolve()))

import openva_vendor_inventory_matcher.matcher as matcher  # noqa: E402
from openva_vendor_inventory_matcher import match_inventory  # noqa: E402


def write_inventory(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = list(rows[0]) if rows else ["vendor_name", "domain", "category"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_domain_exact_match_enriches_stripe(tmp_path):
    input_path = tmp_path / "vendors.csv"
    output_path = tmp_path / "matched.csv"
    write_inventory(input_path, [{"vendor_name": "Stripe", "domain": "stripe.com", "category": "payments"}])

    result = match_inventory(".", input_path, output_path)

    assert result == output_path
    row = read_csv(output_path)[0]
    assert row["vendor_name"] == "Stripe"
    assert row["category"] == "payments"
    assert row["match_status"] == "matched"
    assert row["matched_vendor_id"] == "stripe"
    assert row["matched_display_name"] == "Stripe"
    assert row["match_confidence"] == "1.00"
    assert row["match_method"] == "domain_exact"
    assert row["manifest_path"] == "dist/vendors/stripe.json"
    assert row["record_class"] == "inventory_match"
    assert row["canonical"] == "false"
    assert row["advisory_boundary"] == "non_advisory"


def test_subdomain_match_requires_dot_boundary(tmp_path):
    input_path = tmp_path / "vendors.csv"
    output_path = tmp_path / "matched.csv"
    write_inventory(
        input_path,
        [
            {"vendor_name": "", "domain": "app.slack.com", "category": "collaboration"},
            {"vendor_name": "", "domain": "evilstripe.com", "category": "lookalike"},
        ],
    )

    match_inventory(".", input_path, output_path)

    rows = read_csv(output_path)
    assert rows[0]["matched_vendor_id"] == "slack"
    assert rows[0]["match_method"] == "domain_subdomain"
    assert rows[0]["match_confidence"] == "0.95"
    assert rows[1]["match_status"] == "no_match"
    assert rows[1]["matched_vendor_id"] == ""
    assert json.loads(rows[1]["candidate_matches_json"]) == []


def test_exact_normalized_name_match_works_without_domain(tmp_path):
    input_path = tmp_path / "vendors.csv"
    output_path = tmp_path / "matched.csv"
    write_inventory(input_path, [{"vendor_name": "Slack", "domain": "", "category": "collaboration"}])

    match_inventory(".", input_path, output_path)

    row = read_csv(output_path)[0]
    assert row["match_status"] == "matched"
    assert row["matched_vendor_id"] == "slack"
    assert row["match_confidence"] == "0.90"
    assert row["match_method"] == "name_exact"


def test_business_entity_name_match_works_without_vendor_name_or_domain(tmp_path):
    input_path = tmp_path / "vendors.csv"
    output_path = tmp_path / "matched.csv"
    write_inventory(input_path, [{"business_entity_name": "Slack Technologies LLC"}])

    match_inventory(".", input_path, output_path)

    row = read_csv(output_path)[0]
    assert row["business_entity_name"] == "Slack Technologies LLC"
    assert row["match_status"] == "matched"
    assert row["matched_vendor_id"] == "slack"
    assert row["match_confidence"] == "0.90"
    assert row["match_method"] == "name_exact"


def test_normalized_legal_suffix_name_match_works_without_domain(monkeypatch, tmp_path):
    monkeypatch.setattr(matcher.OpenVAPack, "load", lambda _: SyntheticPack.single_match())
    input_path = tmp_path / "vendors.csv"
    output_path = tmp_path / "matched.csv"
    write_inventory(input_path, [{"vendor_name": "Acme", "domain": "", "category": "test"}])

    match_inventory("unused-pack-path", input_path, output_path)

    row = read_csv(output_path)[0]
    assert row["match_status"] == "matched"
    assert row["matched_vendor_id"] == "acme"
    assert row["match_confidence"] == "0.90"
    assert row["match_method"] == "name_exact"


def test_single_above_threshold_candidate_is_not_ambiguous(monkeypatch, tmp_path):
    monkeypatch.setattr(matcher.OpenVAPack, "load", lambda _: SyntheticPack.single_match())
    input_path = tmp_path / "vendors.csv"
    output_path = tmp_path / "matched.csv"
    write_inventory(input_path, [{"vendor_name": "Acme", "domain": "", "category": "test"}])

    match_inventory("unused-pack-path", input_path, output_path)

    row = read_csv(output_path)[0]
    assert row["match_status"] == "matched"
    assert row["matched_vendor_id"] == "acme"
    assert row["match_confidence"] == "0.90"
    assert len(json.loads(row["candidate_matches_json"])) == 1


def test_tied_candidates_are_ambiguous(monkeypatch, tmp_path):
    monkeypatch.setattr(matcher.OpenVAPack, "load", lambda _: SyntheticPack.ambiguous())
    input_path = tmp_path / "vendors.csv"
    output_path = tmp_path / "matched.csv"
    write_inventory(input_path, [{"vendor_name": "Shared Name", "domain": "", "category": "test"}])

    match_inventory("unused-pack-path", input_path, output_path)

    row = read_csv(output_path)[0]
    assert row["match_status"] == "ambiguous"
    assert row["matched_vendor_id"] == ""
    candidates = json.loads(row["candidate_matches_json"])
    assert candidates == [
        {
            "display_name": "Shared Name",
            "match_confidence": 0.9,
            "match_method": "name_exact",
            "vendor_id": "shared-a",
        },
        {
            "display_name": "Shared Name",
            "match_confidence": 0.9,
            "match_method": "name_exact",
            "vendor_id": "shared-b",
        },
    ]


def test_unmatched_rows_preserve_original_columns(tmp_path):
    input_path = tmp_path / "vendors.csv"
    output_path = tmp_path / "matched.csv"
    write_inventory(input_path, [{"vendor_name": "No Such Vendor", "domain": "", "category": "unknown"}])

    match_inventory(".", input_path, output_path)

    row = read_csv(output_path)[0]
    assert row["vendor_name"] == "No Such Vendor"
    assert row["category"] == "unknown"
    assert row["match_status"] == "no_match"
    assert row["matched_vendor_id"] == ""
    assert row["manifest_path"] == ""


def test_json_payloads_are_compact_and_preserve_source_semantics(tmp_path):
    input_path = tmp_path / "vendors.csv"
    output_path = tmp_path / "matched.csv"
    write_inventory(input_path, [{"vendor_name": "Stripe", "domain": "stripe.com", "category": "payments"}])

    match_inventory(".", input_path, output_path)

    row = read_csv(output_path)[0]
    candidate_matches = json.loads(row["candidate_matches_json"])
    assert candidate_matches == [
        {
            "display_name": "Stripe",
            "match_confidence": 1.0,
            "match_method": "domain_exact",
            "vendor_id": "stripe",
        }
    ]
    assert "\n" not in row["canonical_sources_json"]
    assert isinstance(json.loads(row["official_domains_json"]), list)
    assert isinstance(json.loads(row["canonical_source_types_json"]), list)
    canonical_sources = json.loads(row["canonical_sources_json"])
    assert canonical_sources
    assert {"source_id", "source_type", "source_url", "title_en", "effective_or_published_at"} == set(canonical_sources[0])
    assert any(source["source_type"] == "dpa" for source in canonical_sources)
    primary_sources = json.loads(row["primary_source_by_type_json"])
    assert primary_sources["dpa"]["source_type"] == "dpa"
    assert json.loads(row["candidate_sources_json"]) == []
    assert row["canonical_sources_available"] == "true"
    assert row["candidate_sources_available"] == "false"


def test_primary_source_by_type_prefers_newest_dated_source(monkeypatch, tmp_path):
    monkeypatch.setattr(matcher.OpenVAPack, "load", lambda _: SyntheticPack.with_dated_sources())
    input_path = tmp_path / "vendors.csv"
    output_path = tmp_path / "matched.csv"
    write_inventory(input_path, [{"vendor_name": "Acme", "domain": "acme.example", "category": "test"}])

    match_inventory("unused-pack-path", input_path, output_path)

    row = read_csv(output_path)[0]
    primary_sources = json.loads(row["primary_source_by_type_json"])
    assert primary_sources["dpa"]["source_id"] == "acme-dpa-new"
    assert primary_sources["privacy_notice"]["source_id"] == "acme-privacy"


def test_google_domain_collision_matches_specific_subdomain(tmp_path):
    input_path = tmp_path / "vendors.csv"
    output_path = tmp_path / "matched.csv"
    write_inventory(
        input_path,
        [
            {"vendor_name": "Google Workspace", "domain": "workspace.google.com", "category": "productivity"},
            {"vendor_name": "Google Cloud", "domain": "cloud.google.com", "category": "cloud"},
        ],
    )

    match_inventory(".", input_path, output_path)

    rows = read_csv(output_path)
    assert rows[0]["match_status"] == "matched"
    assert rows[0]["matched_vendor_id"] == "google-workspace"
    assert rows[0]["match_confidence"] == "1.00"
    assert rows[0]["match_method"] == "domain_exact"
    assert rows[1]["match_status"] == "matched"
    assert rows[1]["matched_vendor_id"] == "google-cloud"
    assert rows[1]["match_confidence"] == "1.00"
    assert rows[1]["match_method"] == "domain_exact"


def test_google_bare_name_is_ambiguous_between_workspace_and_cloud(tmp_path):
    input_path = tmp_path / "vendors.csv"
    output_path = tmp_path / "matched.csv"
    write_inventory(input_path, [{"vendor_name": "Google", "domain": "", "category": "productivity"}])

    match_inventory(".", input_path, output_path)

    row = read_csv(output_path)[0]
    assert row["match_status"] == "ambiguous"
    candidate_ids = [candidate["vendor_id"] for candidate in json.loads(row["candidate_matches_json"])]
    assert candidate_ids == ["google-cloud", "google-workspace"]


def test_candidate_source_payloads_use_expected_shape(monkeypatch, tmp_path):
    monkeypatch.setattr(matcher.OpenVAPack, "load", lambda _: SyntheticPack.with_candidate_source())
    input_path = tmp_path / "vendors.csv"
    output_path = tmp_path / "matched.csv"
    write_inventory(input_path, [{"vendor_name": "Acme", "domain": "acme.example", "category": "test"}])

    match_inventory("unused-pack-path", input_path, output_path)

    row = read_csv(output_path)[0]
    assert row["candidate_sources_available"] == "true"
    assert json.loads(row["candidate_sources_json"]) == [
        {
            "candidate_source_id": "acme-candidate-dpa",
            "candidate_url": "https://acme.example/dpa",
            "confidence": "medium",
            "source_type_candidate": "dpa",
        }
    ]


def test_unavailable_coverage_and_latest_observation_are_enriched(monkeypatch, tmp_path):
    monkeypatch.setattr(matcher.OpenVAPack, "load", lambda _: SyntheticPack.with_unavailable_and_observations())
    input_path = tmp_path / "vendors.csv"
    output_path = tmp_path / "matched.csv"
    write_inventory(input_path, [{"vendor_name": "Acme", "domain": "acme.example", "category": "test"}])

    match_inventory("unused-pack-path", input_path, output_path)

    row = read_csv(output_path)[0]
    assert json.loads(row["unavailable_source_types_json"]) == ["dpa"]
    assert row["unavailable_sources_recorded"] == "true"
    assert row["latest_observation_result"] == "ok"
    assert row["latest_observed_at"] == "2026-05-20T00:00:00Z"


def test_output_does_not_emit_risk_or_approval_fields(tmp_path):
    input_path = tmp_path / "vendors.csv"
    output_path = tmp_path / "matched.csv"
    write_inventory(input_path, [{"vendor_name": "Stripe", "domain": "stripe.com", "category": "payments"}])

    match_inventory(".", input_path, output_path)

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        fieldnames = csv.DictReader(handle).fieldnames
    assert fieldnames is not None
    forbidden_fragments = ["risk", "approval", "approved", "suitability"]
    assert not any(fragment in field.lower() for fragment in forbidden_fragments for field in fieldnames)


def test_input_requires_matchable_identity_column(tmp_path):
    input_path = tmp_path / "vendors.csv"
    output_path = tmp_path / "matched.csv"
    write_inventory(input_path, [{"name": "Stripe", "website": "stripe.com"}])

    with pytest.raises(ValueError, match="domain, vendor_name, or business_entity_name"):
        match_inventory(".", input_path, output_path)


def test_console_script_entrypoint_is_declared():
    pyproject = tomllib.loads(
        Path("adapters/python/openva_vendor_inventory_matcher/pyproject.toml").read_text(encoding="utf-8")
    )

    assert (
        pyproject["project"]["scripts"]["openva-vendor-inventory-match"]
        == "openva_vendor_inventory_matcher.cli:main"
    )


def test_module_cli_writes_enriched_csv(tmp_path):
    input_path = tmp_path / "vendors.csv"
    output_path = tmp_path / "matched.csv"
    write_inventory(input_path, [{"vendor_name": "Stripe", "domain": "stripe.com", "category": "payments"}])
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(Path("adapters/python/openva_pack_reader").resolve()),
            str(Path("adapters/python/openva_vendor_inventory_matcher").resolve()),
        ]
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "openva_vendor_inventory_matcher",
            "--pack",
            ".",
            "--input",
            str(input_path),
            "--out",
            str(output_path),
        ],
        check=False,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert read_csv(output_path)[0]["matched_vendor_id"] == "stripe"


class SyntheticPack:
    def __init__(
        self,
        vendors: list[dict[str, object]],
        coverage: list[dict[str, object]] | None = None,
        candidates: list[dict[str, object]] | None = None,
        observations: list[dict[str, object]] | None = None,
        sources: list[dict[str, object]] | None = None,
    ):
        self._vendors = vendors
        self._coverage = coverage or []
        self._candidates = candidates or []
        self._observations = observations or []
        self._sources = sources or []

    @classmethod
    def single_match(cls):
        return cls([synthetic_vendor("acme", "Acme", ["acme.example"]), synthetic_vendor("beta", "Beta", ["beta.example"])])

    @classmethod
    def ambiguous(cls):
        return cls(
            [
                synthetic_vendor("shared-a", "Shared Name", ["shared-a.example"]),
                synthetic_vendor("shared-b", "Shared Name", ["shared-b.example"]),
            ]
        )

    @classmethod
    def with_candidate_source(cls):
        return cls(
            [synthetic_vendor("acme", "Acme", ["acme.example"])],
            coverage=[
                {
                    "vendor_id": "acme",
                    "canonical_source_types": [],
                    "candidate_source_types": ["dpa"],
                    "unavailable_source_types": [],
                    "missing_core_source_types": [],
                }
            ],
            candidates=[
                {
                    "vendor_id": "acme",
                    "candidate_source_id": "acme-candidate-dpa",
                    "source_type_candidate": "dpa",
                    "candidate_url": "https://acme.example/dpa",
                    "confidence": "medium",
                }
            ],
        )

    @classmethod
    def with_dated_sources(cls):
        return cls(
            [synthetic_vendor("acme", "Acme", ["acme.example"])],
            coverage=[
                {
                    "vendor_id": "acme",
                    "canonical_source_types": ["dpa", "privacy_notice"],
                    "candidate_source_types": [],
                    "unavailable_source_types": [],
                    "missing_core_source_types": [],
                }
            ],
            sources=[
                {
                    "vendor_id": "acme",
                    "source_id": "acme-dpa-old",
                    "source_type": "dpa",
                    "source_url": "https://acme.example/dpa-old",
                    "title_en": "Acme DPA Old",
                    "effective_or_published_at": "2025-01-01",
                },
                {
                    "vendor_id": "acme",
                    "source_id": "acme-dpa-new",
                    "source_type": "dpa",
                    "source_url": "https://acme.example/dpa-new",
                    "title_en": "Acme DPA New",
                    "effective_or_published_at": "2026-01-01",
                },
                {
                    "vendor_id": "acme",
                    "source_id": "acme-privacy",
                    "source_type": "privacy_notice",
                    "source_url": "https://acme.example/privacy",
                    "title_en": "Acme Privacy",
                    "effective_or_published_at": "",
                },
            ],
        )

    @classmethod
    def with_unavailable_and_observations(cls):
        return cls(
            [synthetic_vendor("acme", "Acme", ["acme.example"])],
            coverage=[
                {
                    "vendor_id": "acme",
                    "canonical_source_types": [],
                    "candidate_source_types": [],
                    "unavailable_source_types": ["dpa"],
                    "missing_core_source_types": ["privacy_notice"],
                }
            ],
            observations=[
                {
                    "vendor_id": "acme",
                    "result": "fetch_failed",
                    "observed_at": "2026-05-19T00:00:00Z",
                },
                {
                    "vendor_id": "acme",
                    "result": "ok",
                    "observed_at": "2026-05-20T00:00:00Z",
                },
            ],
        )

    def vendor_search(self):
        return self._vendors

    def source_coverage(self):
        return {"vendor_coverage": self._coverage}

    def canonical_sources(self):
        return self._sources

    def candidate_sources(self):
        return self._candidates

    def observations(self):
        return self._observations


def synthetic_vendor(vendor_id: str, display_name: str, domains: list[str]) -> dict[str, object]:
    return {
        "vendor_id": vendor_id,
        "display_name": display_name,
        "legal_name": f"{display_name}, Inc.",
        "catalog_status": "active",
        "official_domains": domains,
        "manifest_path": f"dist/vendors/{vendor_id}.json",
    }
