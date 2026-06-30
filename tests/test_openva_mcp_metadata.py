"""Distribution-metadata checks for the MCP package.

Offline checks always run; the Registry-schema validation fetches the official
schema and skips only when the network is unavailable.
"""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "integrations" / "mcp" / "openva_mcp"
SERVER_JSON = PKG / "manifest" / "server.json"
README = PKG / "README.md"
DOCKERFILE = PKG / "Dockerfile"
PYPROJECT = PKG / "pyproject.toml"

# Pinned copy of the official MCP Registry schema, so PR validation is
# deterministic and offline. Provenance is asserted by the digest below.
SCHEMA_URL = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
PINNED_SCHEMA = PKG / "manifest" / "server.schema.2025-12-11.json"
PINNED_SCHEMA_SHA256 = "fe034eb855b202d8b80784eaa24412b5b89084fe9c48c1439226b7487976ed1c"


def _server_json() -> dict:
    return json.loads(SERVER_JSON.read_text(encoding="utf-8"))


def test_server_json_targets_current_schema_and_has_required_fields():
    doc = _server_json()
    assert doc["$schema"] == "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
    assert doc["name"] == "io.github.thedanieltan/openva"
    assert doc["title"]
    assert doc["version"]
    assert doc["packages"][0]["registryType"] == "pypi"
    assert doc["packages"][0]["identifier"] == "openva-mcp"


def test_no_bespoke_manifest_remains():
    # Only the standards-based server.json is kept.
    assert not (PKG / "manifest" / "mcp-manifest.json").exists()


def test_readme_has_pypi_ownership_marker_and_no_false_publication_claim():
    text = README.read_text(encoding="utf-8")
    assert "<!-- mcp-name: io.github.thedanieltan/openva -->" in text
    assert "not yet published to PyPI" in text
    # The bare registry command must not be presented as currently runnable.
    assert "\npipx install openva-mcp\n" not in text


def test_dockerfile_posture_labels_and_non_root():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert 'io.modelcontextprotocol.server.name="io.github.thedanieltan/openva"' in text
    assert "org.opencontainers.image.source=" in text
    assert "org.opencontainers.image.licenses=" in text
    assert "USER openva" in text
    assert "read-only by construction" not in text.lower()


def test_pyproject_pins_mcp_below_v2():
    text = PYPROJECT.read_text(encoding="utf-8")
    assert "mcp>=1.27,<2" in text


def test_pinned_schema_provenance_digest_matches():
    data = PINNED_SCHEMA.read_bytes()
    assert hashlib.sha256(data).hexdigest() == PINNED_SCHEMA_SHA256
    # server.json declares the same schema URL the pinned copy came from.
    assert _server_json()["$schema"] == SCHEMA_URL


def test_server_json_validates_against_pinned_official_schema():
    import jsonschema

    schema = json.loads(PINNED_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(instance=_server_json(), schema=schema)
