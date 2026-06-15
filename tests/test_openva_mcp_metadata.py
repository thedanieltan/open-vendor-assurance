"""Distribution-metadata checks for the MCP package.

Offline checks always run; the Registry-schema validation fetches the official
schema and skips only when the network is unavailable.
"""

import json
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "integrations" / "mcp" / "openva_mcp"
SERVER_JSON = PKG / "manifest" / "server.json"
MCP_MANIFEST = PKG / "manifest" / "mcp-manifest.json"
README = PKG / "README.md"
DOCKERFILE = PKG / "Dockerfile"
PYPROJECT = PKG / "pyproject.toml"

REQUIRED_TOOLS = {
    "search_vendors",
    "get_vendor",
    "list_vendor_sources",
    "get_source",
    "get_source_health",
    "get_vendor_changes",
    "match_inventory",
    "get_snapshot_metadata",
    "verify_snapshot",
}


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


def test_mcp_manifest_lists_all_tools_and_no_secret_requirement():
    doc = json.loads(MCP_MANIFEST.read_text(encoding="utf-8"))
    assert set(doc["tools"]) == REQUIRED_TOOLS
    assert doc["capabilities"]["read_only"] is True
    assert doc["capabilities"]["requires_secrets"] is False


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


def test_server_json_validates_against_official_schema():
    jsonschema = pytest.importorskip("jsonschema")
    url = _server_json()["$schema"]
    try:
        with urlopen(url, timeout=15) as response:  # noqa: S310 - official https schema URL
            schema = json.loads(response.read())
    except (URLError, TimeoutError, OSError) as exc:
        pytest.skip(f"schema not reachable: {exc}")
    jsonschema.validate(instance=_server_json(), schema=schema)
