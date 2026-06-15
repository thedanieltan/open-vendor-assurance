import json
from pathlib import Path

from tools.openva.release_coherence import (
    DEFAULT_CHECKSUMS_NAME,
    DEFAULT_MANIFEST_NAME,
    build_release_manifest,
    check_release_manifest,
    mcp_software_version,
    write_checksums,
)

AGENT_DIGEST = "sha256:" + "a" * 64
PUBLISHED_AT = "2026-06-15T00:00:00Z"


def _asset_dir(tmp_path: Path) -> Path:
    d = tmp_path / "assets"
    d.mkdir()
    (d / "openva-csv.zip").write_bytes(b"zip-bytes")
    (d / "openva_mcp-0.1.0.tar.gz").write_bytes(b"sdist-bytes")
    (d / "openva_mcp-0.1.0-py3-none-any.whl").write_bytes(b"wheel-bytes")
    (d / "server.json").write_text("{}", encoding="utf-8")
    return d


def _manifest(tmp_path: Path) -> dict:
    return build_release_manifest(
        asset_dir=_asset_dir(tmp_path),
        release_tag="v0.1.0",
        commit_sha="deadbeef" + "0" * 32,
        published_at=PUBLISHED_AT,
        agent_digest=AGENT_DIGEST,
    )


def test_manifest_keeps_four_identities_distinct(tmp_path):
    manifest = _manifest(tmp_path)
    ids = manifest["identities"]
    for key in (
        "release_tag",
        "repository_commit_sha",
        "catalog_record_schema_version",
        "export_pack_schema_version",
        "agent_export_schema_version",
        "mcp_software_version",
    ):
        assert key in ids
    # Software version and catalog/export schema are separate fields.
    assert ids["mcp_software_version"] == mcp_software_version()
    assert ids["export_pack_schema_version"] != ids["mcp_software_version"]
    assert ids["release_tag"] == "v0.1.0"
    assert manifest["agent_index_digest"] == AGENT_DIGEST
    assert manifest["not_advice"] is True


def test_manifest_digests_are_computed_from_actual_asset_bytes(tmp_path):
    asset_dir = _asset_dir(tmp_path)
    manifest = build_release_manifest(
        asset_dir=asset_dir,
        release_tag="v0.1.0",
        commit_sha="c" * 40,
        published_at=PUBLISHED_AT,
        agent_digest=AGENT_DIGEST,
    )
    names = {row["name"] for row in manifest["assets"]}
    assert {"openva-csv.zip", "openva_mcp-0.1.0.tar.gz", "openva_mcp-0.1.0-py3-none-any.whl"} <= names
    for row in manifest["assets"]:
        assert row["sha256"].startswith("sha256:")
        assert row["size_bytes"] == (asset_dir / row["name"]).stat().st_size


def test_unpublished_distributions_are_not_claimed(tmp_path):
    manifest = _manifest(tmp_path)
    assert manifest["distributions"] == {
        "pypi_published": False,
        "oci_published": False,
        "mcp_registry_published": False,
    }
    assert manifest["build_provenance"]["signed"] is False
    assert manifest["build_provenance"]["attested"] is False


def test_check_passes_for_consistent_manifest_and_fails_on_tamper(tmp_path):
    asset_dir = _asset_dir(tmp_path)
    manifest = build_release_manifest(
        asset_dir=asset_dir,
        release_tag="v0.1.0",
        commit_sha="c" * 40,
        published_at=PUBLISHED_AT,
        agent_digest=AGENT_DIGEST,
    )
    manifest_path = asset_dir / DEFAULT_MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert check_release_manifest(asset_dir, manifest_path) == []

    # Tamper an asset on disk: digest no longer matches.
    (asset_dir / "openva-csv.zip").write_bytes(b"tampered")
    assert check_release_manifest(asset_dir, manifest_path)


def test_check_rejects_missing_identity(tmp_path):
    asset_dir = _asset_dir(tmp_path)
    manifest = build_release_manifest(
        asset_dir=asset_dir,
        release_tag="v0.1.0",
        commit_sha="c" * 40,
        published_at=PUBLISHED_AT,
        agent_digest=AGENT_DIGEST,
    )
    del manifest["identities"]["mcp_software_version"]
    manifest_path = asset_dir / DEFAULT_MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert any("identities" in failure for failure in check_release_manifest(asset_dir, manifest_path))


def test_checksums_file_lists_every_asset(tmp_path):
    asset_dir = _asset_dir(tmp_path)
    path = write_checksums(asset_dir, exclude={DEFAULT_MANIFEST_NAME, DEFAULT_CHECKSUMS_NAME})
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 4
    for line in lines:
        digest, name = line.split("  ", 1)
        assert len(digest) == 64
        assert (asset_dir / name).is_file()


def test_agent_index_digest_is_real(tmp_path):
    from tools.openva.release_coherence import agent_index_digest

    digest = agent_index_digest("commit" + "0" * 34, PUBLISHED_AT, out_dir=tmp_path / "tree")
    assert digest.startswith("sha256:")
    assert (tmp_path / "tree" / "openva-agent-index.json").is_file()
