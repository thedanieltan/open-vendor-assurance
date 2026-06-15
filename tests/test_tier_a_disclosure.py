"""Tier A: trust-center scope and gated-child non-disclosure at export + MCP.

A public trust-center landing page is a content-bearing source; its gated child
documents are never inspected. The export and MCP layers must disclose that
scope and must never surface gated-child content, hashes, summaries, or inferred
claims.
"""

import json
import sys
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
for _src in (
    ROOT / "integrations" / "mcp" / "openva_mcp",
    ROOT / "adapters" / "python" / "openva_vendor_inventory_matcher",
    ROOT / "adapters" / "python" / "openva_pack_reader",
):
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from openva_mcp import tools  # noqa: E402
from openva_mcp.snapshot import LocalSnapshotSource, Snapshot  # noqa: E402

from tools.openva.agent_export import build_agent_exports  # noqa: E402

SOURCE_SCHEMA = json.loads((ROOT / "schemas/openva/source-reference.schema.json").read_text(encoding="utf-8"))
EXPORT_SCHEMA = json.loads((ROOT / "schemas/openva/agent-export.schema.json").read_text(encoding="utf-8"))

COMMIT = "tadisclose" + "0" * 30
GENERATED_AT = "2026-06-15T00:00:00Z"
ALLOWED_SOURCE_ROW_KEYS = set(EXPORT_SCHEMA["$defs"]["source_row"]["properties"])
BANNED_CONTENT_HINTS = ("hash", "summary", "digest", "raw", "text", "screenshot", "certificat", "report")


def _make_repo(tmp_path: Path) -> Path:
    vendor = tmp_path / "data" / "vendors" / "acme"
    (vendor / "sources").mkdir(parents=True)
    (vendor / "vendor.yaml").write_text(
        "vendor_id: acme\ndisplay_name: Acme\nofficial_domains:\n  - acme.example\n", encoding="utf-8"
    )
    (vendor / "sources" / "acme-trust.yaml").write_text(
        "source_id: acme-trust\nvendor_id: acme\nsource_type: trust_center\n"
        "source_url: https://acme.example/trust\naccess_class: public_landing_gated_docs\n",
        encoding="utf-8",
    )
    (vendor / "sources" / "acme-privacy.yaml").write_text(
        "source_id: acme-privacy\nvendor_id: acme\nsource_type: privacy_notice\n"
        "source_url: https://acme.example/privacy\naccess_class: public_web\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def export_tree(tmp_path) -> Path:
    _make_repo(tmp_path)
    out = tmp_path / "out"
    build_agent_exports(root=tmp_path, out_dir=out, commit_sha=COMMIT, generated_at=GENERATED_AT)
    return out


def _rows(export_tree: Path) -> dict[str, dict]:
    vendor = json.loads((export_tree / "vendors" / "acme.json").read_text(encoding="utf-8"))
    jsonschema.validate(vendor, {"$ref": "#/$defs/vendor_export", "$defs": EXPORT_SCHEMA["$defs"]})
    return {row["source_id"]: row for row in vendor["sources"]}


def test_trust_center_landing_page_discloses_landing_scope(export_tree):
    rows = _rows(export_tree)
    trust = rows["acme-trust"]
    assert trust["verified_scope"] == "landing_page_only"
    assert trust["gated_child_content_observed"] is False


def test_normal_source_discloses_full_content_scope(export_tree):
    rows = _rows(export_tree)
    assert rows["acme-privacy"]["verified_scope"] == "full_content"
    assert rows["acme-privacy"]["gated_child_content_observed"] is False


def test_no_export_row_ever_claims_gated_child_content(export_tree):
    for path in export_tree.rglob("*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for source_list in (doc.get("sources", []),):
            for row in source_list:
                if "gated_child_content_observed" in row:
                    assert row["gated_child_content_observed"] is False


def test_export_rows_carry_no_child_document_content_fields(export_tree):
    rows = _rows(export_tree)
    for row in rows.values():
        # additionalProperties:false already forbids extra keys; assert the row
        # shape is exactly the allowed disclosure set and nothing content-bearing.
        assert set(row).issubset(ALLOWED_SOURCE_ROW_KEYS)
        for key in row:
            assert not any(hint in key.lower() for hint in BANNED_CONTENT_HINTS), key


def test_source_schema_forbids_observed_gated_child_content():
    record = {"gated_child_content_observed": True}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(record, {"properties": SOURCE_SCHEMA["properties"], "type": "object"})
    ok = {"gated_child_content_observed": False, "verified_scope": "landing_page_only"}
    jsonschema.validate(ok, {"properties": SOURCE_SCHEMA["properties"], "type": "object"})


def test_mcp_discloses_scope_and_no_gated_content(export_tree):
    snapshot = Snapshot.load(LocalSnapshotSource(export_tree))

    source = tools.get_source(snapshot, "acme-trust")["source"]
    assert source["verified_scope"] == "landing_page_only"
    assert source["gated_child_content_observed"] is False

    listed = tools.list_vendor_sources(snapshot, "acme")["sources"]
    by_id = {s["source_id"]: s for s in listed}
    assert by_id["acme-trust"]["verified_scope"] == "landing_page_only"
    assert all(s["gated_child_content_observed"] is False for s in listed)
    # No MCP source field carries gated-child content.
    for s in listed:
        for key in s:
            assert not any(hint in key.lower() for hint in ("hash", "summary", "digest", "raw", "screenshot")), key
