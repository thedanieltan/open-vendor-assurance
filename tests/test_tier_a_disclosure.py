"""Tier A: trust-center scope and gated-child non-disclosure at export + MCP.

A public trust-center landing page is a content-bearing source; its gated child
documents are never inspected. verified_scope is a committed classification fact
projected verbatim by the export; gated_child_content_observed is a universal
non-observation doctrine guarantee (always false). Both are optional in the wire
schema (legacy 0.1.0 exports may omit them) but always emitted by current
builders. Absence is never "gated content observed".
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
from tools.openva.source_authority import classify_verified_scope  # noqa: E402

SOURCE_SCHEMA = json.loads((ROOT / "schemas/openva/source-reference.schema.json").read_text(encoding="utf-8"))
EXPORT_SCHEMA = json.loads((ROOT / "schemas/openva/agent-export.schema.json").read_text(encoding="utf-8"))

COMMIT = "tadisclose" + "0" * 30
GENERATED_AT = "2026-06-15T00:00:00Z"
SOURCE_ROW_SUBSCHEMA = {"$ref": "#/$defs/source_row", "$defs": EXPORT_SCHEMA["$defs"]}
BANNED_CONTENT_HINTS = ("hash", "summary", "digest", "raw", "text", "screenshot", "certificat", "report")


def _make_repo(tmp_path: Path) -> Path:
    vendor = tmp_path / "data" / "vendors" / "acme"
    (vendor / "sources").mkdir(parents=True)
    (vendor / "vendor.yaml").write_text(
        "vendor_id: acme\ndisplay_name: Acme\nofficial_domains:\n  - acme.example\n", encoding="utf-8"
    )
    # verified_scope is set by classification on the committed record.
    (vendor / "sources" / "acme-trust.yaml").write_text(
        "source_id: acme-trust\nvendor_id: acme\nsource_type: trust_center\n"
        "source_url: https://acme.example/trust\naccess_class: public_landing_gated_docs\n"
        "verified_scope: landing_page_only\n",
        encoding="utf-8",
    )
    (vendor / "sources" / "acme-privacy.yaml").write_text(
        "source_id: acme-privacy\nvendor_id: acme\nsource_type: privacy_notice\n"
        "source_url: https://acme.example/privacy\naccess_class: public_web\nverified_scope: full_content\n",
        encoding="utf-8",
    )
    # Unclassified scope: the export emits verified_scope null, not full_content.
    (vendor / "sources" / "acme-blog.yaml").write_text(
        "source_id: acme-blog\nvendor_id: acme\nsource_type: other_public_source\n"
        "source_url: https://acme.example/blog\naccess_class: public_web\n",
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


def test_committed_scope_is_projected_verbatim(export_tree):
    rows = _rows(export_tree)
    assert rows["acme-trust"]["verified_scope"] == "landing_page_only"
    assert rows["acme-privacy"]["verified_scope"] == "full_content"
    # Unclassified -> null (never inferred to full_content).
    assert rows["acme-blog"]["verified_scope"] is None


def test_new_exports_always_carry_both_fields_and_never_observe_gated_children(export_tree):
    for path in export_tree.rglob("*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for row in doc.get("sources", []):
            assert "verified_scope" in row
            assert "gated_child_content_observed" in row
            assert row["gated_child_content_observed"] is False


def test_export_rows_carry_no_child_document_content_fields(export_tree):
    allowed = set(EXPORT_SCHEMA["$defs"]["source_row"]["properties"])
    for row in _rows(export_tree).values():
        assert set(row).issubset(allowed)
        for key in row:
            assert not any(hint in key.lower() for hint in BANNED_CONTENT_HINTS), key


def test_legacy_export_without_fields_still_validates():
    # An older 0.1.0 export row that omits the Tier A fields remains valid:
    # they are optional in the wire schema.
    legacy = {
        "source_id": "x",
        "source_type": "dpa",
        "source_url": "https://acme.example/dpa",
        "canonical_confidence": None,
        "retrieval_method": None,
        "machine_readable": None,
        "source_health": None,
        "last_observed_at": None,
        "material_change_since_baseline": None,
    }
    jsonschema.validate(legacy, SOURCE_ROW_SUBSCHEMA)
    # A true is schema-impossible even when present.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**legacy, "gated_child_content_observed": True}, SOURCE_ROW_SUBSCHEMA)


def test_source_schema_forbids_observed_gated_child_content():
    record_props = {"properties": SOURCE_SCHEMA["properties"], "type": "object"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"gated_child_content_observed": True}, record_props)
    jsonschema.validate({"gated_child_content_observed": False, "verified_scope": "landing_page_only"}, record_props)


def test_classify_verified_scope_rule():
    assert classify_verified_scope("public_landing_gated_docs") == "landing_page_only"
    assert classify_verified_scope("public_web") == "full_content"
    assert classify_verified_scope(None) == "full_content"


def test_mcp_preserves_absent_vs_explicit_false(export_tree):
    snapshot = Snapshot.load(LocalSnapshotSource(export_tree))
    source = tools.get_source(snapshot, "acme-trust")["source"]
    assert source["verified_scope"] == "landing_page_only"
    assert source["gated_child_content_observed"] is False

    # A legacy row missing the fields: MCP returns None for both — never true,
    # never collapsed to false.
    legacy_view = tools._source_view("acme", {"source_id": "y", "source_url": "https://acme.example/y"})
    assert legacy_view["verified_scope"] is None
    assert legacy_view["gated_child_content_observed"] is None
