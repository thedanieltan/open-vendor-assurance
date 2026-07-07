import csv
import json
import socket
from io import StringIO
from pathlib import Path

from jsonschema import Draft202012Validator

from tools.openva import resolve_csv
from tools.openva import resolver_result_pack as pack


ROOT = Path(__file__).resolve().parents[1]


def write_index(root: Path) -> None:
    index_dir = root / "indexes"
    index_dir.mkdir(parents=True)
    (index_dir / "vendor-match-index.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "generated_at": "1970-01-01T00:00:00Z",
                "count": 2,
                "items": [
                    {
                        "vendor_id": "acme",
                        "display_name": "Acme",
                        "legal_name": "Acme Inc.",
                        "catalog_status": "active",
                        "official_domains": ["acme.example"],
                        "manifest_path": "dist/vendors/acme.json",
                        "primary_source_by_type": {
                            "trust_center": {
                                "source_id": "acme-trust",
                                "source_type": "trust_center",
                                "source_url": "https://trust.acme.example",
                            },
                            "dpa": {
                                "source_id": "acme-dpa",
                                "source_type": "dpa",
                                "source_url": "https://acme.example/dpa",
                                "candidate_basis": "community_hint",
                            },
                        },
                        "canonical_sources": [],
                        "candidate_sources": [],
                    },
                    {
                        "vendor_id": "beta",
                        "display_name": "Beta",
                        "legal_name": "Beta LLC",
                        "catalog_status": "active",
                        "official_domains": ["beta.example"],
                        "manifest_path": "dist/vendors/beta.json",
                        "primary_source_by_type": {
                            "trust_center": {
                                "source_id": "beta-trust",
                                "source_type": "trust_center",
                                "source_url": "https://beta.example/trust",
                                "candidate_basis": "vendor_asserted",
                            }
                        },
                        "canonical_sources": [],
                        "candidate_sources": [],
                    },
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def write_input(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "vendor_name,business_entity_name,domain,jurisdiction,registration_number,registered_address",
                "Acme,,acme.example,US,123,1 Main St",
                "Beta,,beta.example,US,456,2 Main St",
                "Missing,,missing.example,US,789,3 Main St",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def validate_rows(rows):
    schema = json.loads((ROOT / "schemas/openva/resolver-result-pack.schema.json").read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(rows), key=lambda error: list(error.path))
    assert errors == []


def source(row, source_type):
    return next(item for item in row["sources"] if item["source_type"] == source_type)


def test_cli_reads_csv_preserves_order_and_writes_result_pack_and_flat_csv(tmp_path):
    write_index(tmp_path)
    input_csv = tmp_path / "input.csv"
    out_json = tmp_path / "result-pack.json"
    out_csv = tmp_path / "result-pack.csv"
    write_input(input_csv)

    assert resolve_csv.main(
        [
            str(input_csv),
            "--source-types",
            "trust_center,dpa,status_page",
            "--out-json",
            str(out_json),
            "--out-csv",
            str(out_csv),
            "--catalog-root",
            str(tmp_path),
        ]
    ) == 0

    rows = json.loads(out_json.read_text(encoding="utf-8"))
    validate_rows(rows)

    assert [row["input_index"] for row in rows] == [0, 1, 2]
    assert [row["input_vendor_name"] for row in rows] == ["Acme", "Beta", "Missing"]
    assert rows[0]["matched_vendor_id"] == "acme"
    assert rows[0]["matched_vendor_name"] == "Acme"
    assert rows[2]["identity_status"] == "no_match"
    assert rows[2]["no_match_reason"] == "not_in_reference"

    acme_trust = source(rows[0], "trust_center")
    assert acme_trust == {
        "source_type": "trust_center",
        "status": "not_checked",
        "url": "https://trust.acme.example",
        "candidate_basis": "cached_locator",
        "verification_basis": "not_checked",
        "checked_at": None,
    }
    assert source(rows[0], "dpa")["candidate_basis"] == "community_hint"
    assert source(rows[1], "trust_center")["candidate_basis"] == "vendor_asserted"
    assert source(rows[0], "status_page")["candidate_basis"] == "none"
    assert source(rows[0], "status_page")["verification_basis"] == "not_checked"
    assert source(rows[2], "trust_center")["candidate_basis"] == "none"

    parsed_csv = list(csv.DictReader(StringIO(out_csv.read_text(encoding="utf-8"))))
    assert [row["vendor_name"] for row in parsed_csv] == ["Acme", "Beta", "Missing"]
    assert parsed_csv[0]["openva_trust_center_url"] == "https://trust.acme.example"
    assert parsed_csv[0]["openva_trust_center_status"] == "not_checked"
    assert parsed_csv[0]["openva_trust_center_candidate_basis"] == "cached_locator"
    assert parsed_csv[0]["openva_trust_center_verification_basis"] == "not_checked"
    assert parsed_csv[0]["openva_dpa_candidate_basis"] == "community_hint"
    assert parsed_csv[1]["openva_trust_center_candidate_basis"] == "vendor_asserted"
    assert parsed_csv[2]["openva_identity_status"] == "no_match"


def test_cli_output_columns_are_deterministic(tmp_path):
    write_index(tmp_path)
    input_csv = tmp_path / "input.csv"
    out_json = tmp_path / "result-pack.json"
    out_csv = tmp_path / "result-pack.csv"
    write_input(input_csv)

    args = [
        str(input_csv),
        "--source-types",
        "trust_center,dpa,status_page",
        "--out-json",
        str(out_json),
        "--out-csv",
        str(out_csv),
        "--catalog-root",
        str(tmp_path),
    ]
    resolve_csv.main(args)
    first_json = out_json.read_text(encoding="utf-8")
    first_csv = out_csv.read_text(encoding="utf-8")
    resolve_csv.main(args)

    reader = csv.DictReader(StringIO(first_csv))
    assert reader.fieldnames == [
        "vendor_name",
        "business_entity_name",
        "domain",
        "jurisdiction",
        "registration_number",
        "registered_address",
        *pack.FLAT_RESULT_COLUMNS,
    ]
    assert out_json.read_text(encoding="utf-8") == first_json
    assert out_csv.read_text(encoding="utf-8") == first_csv


def test_hint_only_compiler_never_emits_live_verification_or_found(tmp_path, monkeypatch):
    write_index(tmp_path)
    input_rows = [
        {"vendor_name": "Acme", "domain": "acme.example"},
        {"vendor_name": "Beta", "domain": "beta.example"},
    ]

    def fail_socket(*args, **kwargs):
        raise AssertionError("resolve_csv must not use network sockets")

    monkeypatch.setattr(socket, "socket", fail_socket)
    rows = resolve_csv.compile_rows(input_rows, ["trust_center", "dpa"], catalog_root=tmp_path)

    for row in rows:
        for item in row["sources"]:
            assert item["status"] == "not_checked"
            assert item["verification_basis"] == "not_checked"
            assert item["verification_basis"] not in {
                "verified_live",
                "live_unavailable",
                "live_gated",
                "live_not_found",
            }


def test_result_pack_schema_requires_candidate_and_verification_basis(tmp_path):
    write_index(tmp_path)
    rows = resolve_csv.compile_rows(
        [{"vendor_name": "Acme", "domain": "acme.example"}],
        ["trust_center"],
        catalog_root=tmp_path,
    )
    validate_rows(rows)

    schema = json.loads((ROOT / "schemas/openva/resolver-result-pack.schema.json").read_text(encoding="utf-8"))
    missing_candidate = json.loads(json.dumps(rows))
    missing_verification = json.loads(json.dumps(rows))
    del missing_candidate[0]["sources"][0]["candidate_basis"]
    del missing_verification[0]["sources"][0]["verification_basis"]

    assert list(Draft202012Validator(schema).iter_errors(missing_candidate))
    assert list(Draft202012Validator(schema).iter_errors(missing_verification))


def test_docs_describe_hint_only_index_and_consumer_side_live_verification():
    text = (ROOT / "docs/local-compiler.md").read_text(encoding="utf-8")

    assert "hint-only" in text
    assert "does not make network calls" in text
    assert "consumer-side live verification" in text


def test_release_readiness_docs_preserve_local_compiler_entrypoint():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    local_compiler = (ROOT / "docs/local-compiler.md").read_text(encoding="utf-8")
    site_readme = (ROOT / "site/README.md").read_text(encoding="utf-8")

    assert "docs/local-compiler.md" in readme
    assert "python -m tools.openva.resolve_csv" in readme
    assert "python -m tools.openva.resolve_csv input.csv" in local_compiler
    assert "--out-json result-pack.json" in local_compiler
    assert "--out-csv result-pack.csv" in local_compiler
    assert "does not make network calls" in local_compiler
    assert "consumer-side live verification" in local_compiler
    assert "no hosted resolver worker" in site_readme
