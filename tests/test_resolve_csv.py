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
                        "canonical_sources": [
                            {
                                "source_id": "acme-trust",
                                "source_type": "trust_center",
                                "source_url": "https://trust.acme.example",
                            },
                            {
                                "source_id": "acme-dpa",
                                "source_type": "dpa",
                                "source_url": "https://acme.example/dpa",
                            },
                        ],
                    },
                    {
                        "vendor_id": "beta",
                        "display_name": "Beta",
                        "legal_name": "Beta LLC",
                        "catalog_status": "active",
                        "official_domains": ["beta.example"],
                        "manifest_path": "dist/vendors/beta.json",
                        "canonical_sources": [
                            {
                                "source_id": "beta-security",
                                "source_type": "security_page",
                                "source_url": "https://beta.example/security",
                            }
                        ],
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


def test_cli_reads_csv_preserves_order_and_writes_compiled_vendor_files(tmp_path):
    write_index(tmp_path)
    input_csv = tmp_path / "input.csv"
    out_json = tmp_path / "compiled-vendors.json"
    out_csv = tmp_path / "compiled-vendors.csv"
    write_input(input_csv)

    assert resolve_csv.main(
        [
            str(input_csv),
            "--source-types",
            "trust_security,dpa,status_page",
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
    assert rows[0]["matched_vendor_name"] == "Acme"
    assert rows[0]["official_domain"] == "acme.example"
    assert rows[0]["dpa_url"] == "https://acme.example/dpa"
    assert rows[0]["trust_security_url"] == "https://trust.acme.example"
    assert rows[1]["trust_security_url"] == "https://beta.example/security"
    assert rows[2]["matched_vendor_name"] is None
    assert rows[2]["official_domain"] is None
    assert rows[2]["dpa_url"] is None
    assert rows[2]["trust_security_url"] is None

    parsed_csv = list(csv.DictReader(StringIO(out_csv.read_text(encoding="utf-8"))))
    assert [row["vendor_name"] for row in parsed_csv] == ["Acme", "Beta", "Missing"]
    assert parsed_csv[0]["business_entity_name"] == ""
    assert parsed_csv[0]["matched_vendor_name"] == "Acme"
    assert parsed_csv[0]["dpa_url"] == "https://acme.example/dpa"
    assert parsed_csv[0]["trust_security_url"] == "https://trust.acme.example"
    assert parsed_csv[2]["matched_vendor_name"] == ""
    assert parsed_csv[2]["dpa_url"] == ""
    assert "openva_not_advice" not in parsed_csv[0]
    assert not any(column.startswith("openva_") for column in parsed_csv[0])
    assert "compiled_vendor_name" not in parsed_csv[0]
    assert "compiled_domain" not in parsed_csv[0]
    assert "security_or_trust_url" not in parsed_csv[0]
    assert "match_status" not in parsed_csv[0]
    assert "match_reason" not in parsed_csv[0]
    assert "source_status" not in parsed_csv[0]
    assert "review_note" not in parsed_csv[0]


def test_cli_output_columns_are_deterministic(tmp_path):
    write_index(tmp_path)
    input_csv = tmp_path / "input.csv"
    out_json = tmp_path / "compiled-vendors.json"
    out_csv = tmp_path / "compiled-vendors.csv"
    write_input(input_csv)

    args = [
        str(input_csv),
        "--source-types",
        "trust_security,dpa,status_page",
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


def test_compiler_preserves_blank_user_input_fields(tmp_path):
    write_index(tmp_path)
    input_csv = tmp_path / "input.csv"
    out_json = tmp_path / "compiled-vendors.json"
    out_csv = tmp_path / "compiled-vendors.csv"
    input_csv.write_text(
        "vendor_name,business_entity_name,domain,jurisdiction,registration_number,registered_address\n"
        "Acme,,acme.example,US,,\n",
        encoding="utf-8",
    )

    resolve_csv.main(
        [
            str(input_csv),
            "--out-json",
            str(out_json),
            "--out-csv",
            str(out_csv),
            "--catalog-root",
            str(tmp_path),
        ]
    )

    parsed_csv = list(csv.DictReader(StringIO(out_csv.read_text(encoding="utf-8"))))
    assert parsed_csv[0]["business_entity_name"] == ""
    assert parsed_csv[0]["registration_number"] == ""
    assert parsed_csv[0]["registered_address"] == ""
    assert "Unavailable" not in out_csv.read_text(encoding="utf-8")


def test_hint_only_compiler_does_not_use_network(tmp_path, monkeypatch):
    write_index(tmp_path)
    input_rows = [
        {"vendor_name": "Acme", "domain": "acme.example"},
        {"vendor_name": "Beta", "domain": "beta.example"},
    ]

    def fail_socket(*args, **kwargs):
        raise AssertionError("resolve_csv must not use network sockets")

    monkeypatch.setattr(socket, "socket", fail_socket)
    rows = resolve_csv.compile_rows(input_rows, ["trust_security", "dpa"], catalog_root=tmp_path)

    assert rows[0]["dpa_url"] == "https://acme.example/dpa"
    assert rows[1]["trust_security_url"] == "https://beta.example/security"


def test_result_pack_schema_rejects_retired_status_reason_and_advice_fields(tmp_path):
    write_index(tmp_path)
    rows = resolve_csv.compile_rows(
        [{"vendor_name": "Acme", "domain": "acme.example"}],
        ["trust_security"],
        catalog_root=tmp_path,
    )
    validate_rows(rows)

    schema = json.loads((ROOT / "schemas/openva/resolver-result-pack.schema.json").read_text(encoding="utf-8"))
    polluted = json.loads(json.dumps(rows))
    polluted[0]["compiled_vendor_name"] = "Acme"
    polluted[0]["compiled_domain"] = "acme.example"
    polluted[0]["security_or_trust_url"] = "https://trust.acme.example"
    polluted[0]["match_status"] = "matched"
    polluted[0]["match_reason"] = "domain match"
    polluted[0]["source_status"] = "compiled_from_reference"
    polluted[0]["review_note"] = "Review compiled links before relying on them"
    polluted[0]["openva_not_advice"] = True

    assert list(Draft202012Validator(schema).iter_errors(polluted))


def test_docs_describe_simple_compiled_vendor_download():
    text = (ROOT / "docs/local-compiler.md").read_text(encoding="utf-8")

    assert "matched vendor identity" in text
    assert "does not make network calls" in text
    assert "matched_vendor_name" in text
    assert "trust_security_url" in text
    assert "security_or_trust_url" not in text
    assert "match_status" not in text
    assert "source_status" not in text


def test_release_readiness_docs_preserve_local_compiler_entrypoint():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    local_compiler = (ROOT / "docs/local-compiler.md").read_text(encoding="utf-8")
    site_readme = (ROOT / "site/README.md").read_text(encoding="utf-8")

    assert "docs/local-compiler.md" in readme
    assert "python -m tools.openva.resolve_csv" in readme
    assert "python -m tools.openva.resolve_csv input.csv" in local_compiler
    assert "--out-json compiled-vendors.json" in local_compiler
    assert "--out-csv compiled-vendors.csv" in local_compiler
    assert "does not make network calls" in local_compiler
    assert "no hosted resolver worker" in site_readme
