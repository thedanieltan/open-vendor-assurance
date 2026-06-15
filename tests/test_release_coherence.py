import json
from pathlib import Path

from tools.openva.agent_export import build_agent_exports
from tools.openva.release_coherence import (
    DEFAULT_CHECKSUMS_NAME,
    DEFAULT_MANIFEST_NAME,
    build_release_manifest,
    check_release_manifest,
    mcp_software_version,
    read_release_agent_index,
    write_checksums,
)

PUBLISHED_AT = "2026-06-15T00:00:00Z"
COMMIT = "deadbeef" + "0" * 32
ARCHIVE = "openva-agent-exports.zip"


def _asset_dir(tmp_path: Path, commit: str = COMMIT) -> Path:
    d = tmp_path / "assets"
    d.mkdir()
    # Release assets.
    (d / "openva-csv.zip").write_bytes(b"zip-bytes")
    (d / ARCHIVE).write_bytes(b"agent-export-archive-bytes")
    mcp = d / "mcp"
    mcp.mkdir()
    (mcp / "openva_mcp-0.1.0-py3-none-any.whl").write_bytes(b"wheel-bytes")
    # Staged agent-export tree (zipped into ARCHIVE; not a separate asset).
    build_agent_exports(out_dir=d / "agent-exports" / "public", commit_sha=commit, generated_at=PUBLISHED_AT)
    return d


def _index_path(asset_dir: Path) -> Path:
    return asset_dir / "agent-exports" / "public" / "openva-agent-index.json"


def _manifest(asset_dir: Path, commit: str = COMMIT) -> dict:
    return build_release_manifest(
        asset_dir=asset_dir,
        release_tag="v0.1.0",
        commit_sha=commit,
        published_at=PUBLISHED_AT,
        agent_index_path=_index_path(asset_dir),
        agent_archive_name=ARCHIVE,
    )


def test_manifest_keeps_four_identities_distinct(tmp_path):
    ids = _manifest(_asset_dir(tmp_path))["identities"]
    for key in (
        "release_tag",
        "repository_commit_sha",
        "catalog_record_schema_version",
        "export_pack_schema_version",
        "agent_export_schema_version",
        "mcp_software_version",
    ):
        assert key in ids
    assert ids["mcp_software_version"] == mcp_software_version()
    assert ids["export_pack_schema_version"] != ids["mcp_software_version"]


def test_agent_export_block_is_read_from_attached_bytes(tmp_path):
    asset_dir = _asset_dir(tmp_path)
    manifest = _manifest(asset_dir)
    agent = manifest["agent_export"]
    # Digest recorded is exactly the staged index's declared+recomputed digest.
    declared = json.loads(_index_path(asset_dir).read_text(encoding="utf-8"))["snapshot"]["digest"]
    assert agent["index_digest"] == declared == manifest["agent_index_digest"]
    assert agent["archive_asset"] == ARCHIVE
    assert agent["index_path_in_archive"] == "public/openva-agent-index.json"
    assert agent["observation_input"] in ("committed_events_fallback", "none", "run_artifact")
    assert agent["snapshot_commit_sha"] == COMMIT
    # The staged tree is not listed as a separate asset; the zip is.
    names = {row["name"] for row in manifest["assets"]}
    assert ARCHIVE in names
    assert not any(name.startswith("agent-exports/") for name in names)


def test_release_commit_must_match_export_snapshot_commit(tmp_path):
    asset_dir = _asset_dir(tmp_path, commit="a" * 40)
    import pytest

    with pytest.raises(ValueError):
        build_release_manifest(
            asset_dir=asset_dir,
            release_tag="v0.1.0",
            commit_sha="b" * 40,  # different from the export snapshot commit
            published_at=PUBLISHED_AT,
            agent_index_path=_index_path(asset_dir),
            agent_archive_name=ARCHIVE,
        )


def test_read_agent_index_rejects_digest_that_does_not_recompute(tmp_path):
    asset_dir = _asset_dir(tmp_path)
    index = _index_path(asset_dir)
    doc = json.loads(index.read_text(encoding="utf-8"))
    doc["counts"] = {"vendors": 999}  # mutate payload, leave digest stale
    index.write_text(json.dumps(doc), encoding="utf-8")
    import pytest

    with pytest.raises(ValueError):
        read_release_agent_index(index)


def test_unpublished_distributions_are_not_claimed(tmp_path):
    manifest = _manifest(_asset_dir(tmp_path))
    assert manifest["distributions"] == {
        "pypi_published": False,
        "oci_published": False,
        "mcp_registry_published": False,
    }
    assert manifest["build_provenance"]["signed"] is False


def test_check_passes_then_fails_on_tamper(tmp_path):
    asset_dir = _asset_dir(tmp_path)
    manifest = _manifest(asset_dir)
    manifest_path = asset_dir / DEFAULT_MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert check_release_manifest(asset_dir, manifest_path) == []

    (asset_dir / "openva-csv.zip").write_bytes(b"tampered")
    assert check_release_manifest(asset_dir, manifest_path)


def test_checksums_file_excludes_staging_and_self(tmp_path):
    asset_dir = _asset_dir(tmp_path)
    path = write_checksums(asset_dir)
    names = [line.split("  ", 1)[1] for line in path.read_text(encoding="utf-8").strip().splitlines()]
    assert ARCHIVE in names
    assert DEFAULT_CHECKSUMS_NAME not in names
    assert not any(n.startswith("agent-exports/") for n in names)
