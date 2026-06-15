import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from tools.openva.agent_export import build_agent_exports, payload_digest
from tools.openva.deterministic_zip import build_deterministic_zip
from tools.openva.release_coherence import (
    DEFAULT_CHECKSUMS_NAME,
    DEFAULT_MANIFEST_NAME,
    build_release_manifest,
    check_release_manifest,
    mcp_software_version,
    read_agent_index_from_archive,
    write_checksums,
)

PUBLISHED_AT = "2026-06-15T12:00:00Z"
COMMIT = "deadbeef" + "0" * 32
ARCHIVE = "openva-agent-exports.zip"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_archive(base: Path, *, commit: str = COMMIT, arcname_root: str = "public", tamper=None) -> Path:
    staging = base / "staging"
    build_agent_exports(out_dir=staging, commit_sha=commit, generated_at=PUBLISHED_AT)
    if tamper is not None:
        tamper(staging)
    archive = base / "out.zip"
    build_deterministic_zip(staging, archive, arcname_root=arcname_root, generated_at=PUBLISHED_AT)
    return archive


def _asset_dir(tmp_path: Path, *, commit: str = COMMIT) -> Path:
    d = tmp_path / "assets"
    d.mkdir()
    (d / "openva-csv.zip").write_bytes(b"zip-bytes")
    (d / "openva-mcp-wheelhouse-linux-x86_64-py312.zip").write_bytes(b"wheelhouse-bytes")
    shutil.copy(_build_archive(tmp_path / "build", commit=commit), d / ARCHIVE)
    return d


def _manifest(asset_dir: Path, *, commit: str = COMMIT) -> dict:
    return build_release_manifest(
        asset_dir=asset_dir,
        release_tag="v0.1.0",
        commit_sha=commit,
        published_at=PUBLISHED_AT,
        agent_archive_path=asset_dir / ARCHIVE,
        agent_archive_name=ARCHIVE,
    )


def test_export_and_archive_are_byte_deterministic(tmp_path):
    a = _build_archive(tmp_path / "a")
    b = _build_archive(tmp_path / "b")
    assert a.read_bytes() == b.read_bytes()
    assert _sha256(a) == _sha256(b)


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


def test_agent_export_block_is_read_from_the_archive(tmp_path):
    asset_dir = _asset_dir(tmp_path)
    manifest = _manifest(asset_dir)
    agent = manifest["agent_export"]
    archived = read_agent_index_from_archive(asset_dir / ARCHIVE)
    assert agent["index_digest"] == archived["digest"] == manifest["agent_index_digest"]
    assert agent["declared_digest"] == agent["recomputed_digest"]
    assert agent["archive_asset"] == ARCHIVE
    assert agent["index_path_in_archive"] == "public/openva-agent-index.json"
    assert agent["snapshot_commit_sha"] == COMMIT
    assert agent["generated_at"] == PUBLISHED_AT
    names = {row["name"] for row in manifest["assets"]}
    assert ARCHIVE in names
    assert "openva-mcp-wheelhouse-linux-x86_64-py312.zip" in names


def test_every_asset_name_is_root_level_with_no_staging_prefix(tmp_path):
    asset_dir = _asset_dir(tmp_path)
    # Stage a loose wheelhouse dir that must NOT appear as published assets.
    (asset_dir / "mcp-wheelhouse").mkdir()
    (asset_dir / "mcp-wheelhouse" / "openva_mcp-0.1.0-py3-none-any.whl").write_bytes(b"w")
    manifest = _manifest(asset_dir)
    for row in manifest["assets"]:
        assert "/" not in row["name"], row["name"]
        assert not row["name"].startswith(("mcp-wheelhouse", "agent-exports"))


def test_missing_index_in_archive_fails(tmp_path):
    base = tmp_path / "b"
    staging = base / "staging"
    staging.mkdir(parents=True)
    (staging / "unrelated.json").write_text("{}", encoding="utf-8")
    archive = base / "out.zip"
    build_deterministic_zip(staging, archive, arcname_root="public", generated_at=PUBLISHED_AT)
    with pytest.raises(ValueError):
        read_agent_index_from_archive(archive)


def test_wrong_internal_index_path_fails(tmp_path):
    # arcname_root="" puts the index at the root, not under public/.
    archive = _build_archive(tmp_path / "b", arcname_root="")
    with pytest.raises(ValueError):
        read_agent_index_from_archive(archive)


def test_archived_index_differing_from_staged_source_is_the_authority(tmp_path):
    # The archive is built from commit A; a different staging tree (commit B)
    # exists on disk. The manifest must reflect the archive (A), not B.
    asset_dir = _asset_dir(tmp_path, commit=COMMIT)
    other_staging = tmp_path / "other"
    build_agent_exports(out_dir=other_staging, commit_sha="b" * 40, generated_at=PUBLISHED_AT)
    manifest = _manifest(asset_dir)
    assert manifest["agent_export"]["snapshot_commit_sha"] == COMMIT


def test_tampered_archived_index_fails(tmp_path):
    def tamper(staging: Path) -> None:
        index = staging / "openva-agent-index.json"
        doc = json.loads(index.read_text(encoding="utf-8"))
        doc["counts"] = {"vendors": 999}  # mutate payload, leave declared digest stale
        index.write_text(json.dumps(doc), encoding="utf-8")

    archive = _build_archive(tmp_path / "b", tamper=tamper)
    with pytest.raises(ValueError):
        read_agent_index_from_archive(archive)


def test_release_commit_must_match_archive_commit(tmp_path):
    asset_dir = _asset_dir(tmp_path, commit="a" * 40)
    with pytest.raises(ValueError):
        build_release_manifest(
            asset_dir=asset_dir,
            release_tag="v0.1.0",
            commit_sha="b" * 40,
            published_at=PUBLISHED_AT,
            agent_archive_path=asset_dir / ARCHIVE,
            agent_archive_name=ARCHIVE,
        )


def test_check_reopens_archive_and_detects_swap(tmp_path):
    asset_dir = _asset_dir(tmp_path)
    manifest = _manifest(asset_dir)
    manifest_path = asset_dir / DEFAULT_MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert check_release_manifest(asset_dir, manifest_path) == []

    # Swap the archive for a different-commit one: check must fail without the
    # loose staging tree being present.
    shutil.copy(_build_archive(tmp_path / "swap", commit="c" * 40), asset_dir / ARCHIVE)
    assert check_release_manifest(asset_dir, manifest_path)


def test_unpublished_distributions_are_not_claimed(tmp_path):
    manifest = _manifest(_asset_dir(tmp_path))
    assert manifest["distributions"] == {
        "pypi_published": False,
        "oci_published": False,
        "mcp_registry_published": False,
    }
    assert manifest["build_provenance"]["signed"] is False


def test_checksums_file_excludes_staging_and_self(tmp_path):
    asset_dir = _asset_dir(tmp_path)
    (asset_dir / "agent-exports" / "public").mkdir(parents=True)
    (asset_dir / "agent-exports" / "public" / "openva-agent-index.json").write_text("{}", encoding="utf-8")
    path = write_checksums(asset_dir)
    names = [line.split("  ", 1)[1] for line in path.read_text(encoding="utf-8").strip().splitlines()]
    assert ARCHIVE in names
    assert DEFAULT_CHECKSUMS_NAME not in names
    assert not any(n.startswith(("agent-exports/", "mcp-wheelhouse/")) for n in names)
    assert zipfile.is_zipfile(asset_dir / ARCHIVE)
