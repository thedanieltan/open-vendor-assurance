import json
from pathlib import Path

import jsonschema

from tools.openva.agent_export import legal_entity_projection


SCHEMA = json.loads(Path("schemas/openva/agent-export.schema.json").read_text(encoding="utf-8"))


def subschema(name: str) -> dict:
    return {"$ref": f"#/$defs/{name}", "$defs": SCHEMA["$defs"]}


def test_agent_export_projects_typed_legal_identifier_fields():
    projection = legal_entity_projection(
        {
            "entity_id": "cloudflare-inc",
            "vendor_id": "cloudflare",
            "legal_name": "Cloudflare, Inc.",
            "jurisdiction": "US",
            "registration_number": "0001477333",
            "identifier_scheme": "US_SEC_CIK",
            "identifier_authority": "United States Securities and Exchange Commission",
            "identifier_authority_url": "https://www.sec.gov/edgar",
            "catalog_status": "canonical",
            "registered_address": None,
        }
    )

    assert projection["registration_number"] == "0001477333"
    assert projection["identifier_scheme"] == "US_SEC_CIK"
    assert projection["identifier_authority"] == "United States Securities and Exchange Commission"
    assert projection["identifier_authority_url"] == "https://www.sec.gov/edgar"
    jsonschema.validate(projection, subschema("legal_entity"))


def test_agent_export_keeps_legacy_legal_entities_backward_compatible():
    projection = legal_entity_projection(
        {
            "entity_id": "example-sg",
            "vendor_id": "example",
            "legal_name": "Example Singapore Pte. Ltd.",
            "jurisdiction": "SG",
            "registration_number": "202000001A",
            "catalog_status": "canonical",
            "registered_address": None,
        }
    )

    assert "identifier_scheme" not in projection
    assert "identifier_authority" not in projection
    assert "identifier_authority_url" not in projection
    jsonschema.validate(projection, subschema("legal_entity"))
