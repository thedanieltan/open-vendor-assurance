"""Snapshot hardening: path containment, URL validation, and cache integrity.

A snapshot is the trust boundary, so escape and mismatch cases must fail closed.
Cache use must be disclosed; a cached tree is acceptable only while every file
still verifies against the same root index.
"""

import json
import os
import sys
from pathlib import Path

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
from openva_mcp.snapshot import (  # noqa: E402
    AGENT_INDEX_FILE,
    LocalSnapshotSource,
    RemoteSnapshotSource,
    Snapshot,
    SnapshotError,
    SnapshotIntegrityError,
    SnapshotUnsupportedSchemaError,
    payload_digest,
)

from tests.test_agent_export import build, make_repo, run_artifact, write_ledger_event  # noqa: E402


@pytest.fixture
def export_tree(tmp_path) -> Path:
    make_repo(tmp_path)
    write_ledger_event(tmp_path, observed_at="2026-06-01T05:30:00Z")
    return build(tmp_path, latest_observations=run_artifact())


# --- local path containment ----------------------------------------------


def test_local_source_rejects_absolute_and_traversal(export_tree):
    source = LocalSnapshotSource(export_tree)
    for rel in ("/etc/passwd", "C:/Windows/win.ini", "../outside.json", "vendors/../../secret"):
        with pytest.raises(SnapshotError):
            source.read_bytes(rel)


def test_local_source_rejects_missing_file(export_tree):
    with pytest.raises(SnapshotError):
        LocalSnapshotSource(export_tree).read_bytes("vendors/no-such-vendor.json")


def test_local_source_rejects_symlink_escape(export_tree, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("private", encoding="utf-8")
    link = export_tree / "escape"
    try:
        os.symlink(secret, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted in this environment")
    with pytest.raises(SnapshotError):
        LocalSnapshotSource(export_tree).read_bytes("escape")


# --- remote URL validation ------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "ftp://host/tree/",
        "file:///etc/",
        "https://user:pass@host/tree/",
        "https://host/tree/#frag",
        "notaurl",
    ],
)
def test_remote_source_rejects_unsafe_base_urls(url):
    with pytest.raises(SnapshotError):
        RemoteSnapshotSource(url)


def test_remote_source_normalizes_trailing_slash():
    assert RemoteSnapshotSource("https://host/tree").base_url == "https://host/tree/"
    assert RemoteSnapshotSource("https://host/tree/").base_url == "https://host/tree/"


# --- cache provenance & integrity -----------------------------------------


def _reader(root: Path, fail: set[str] | None = None):
    fail = fail or set()

    def fetch(url: str) -> bytes:
        rel = url.split("tree/", 1)[1]
        if rel in fail:
            raise OSError(f"forced network failure for {rel}")
        return (root / rel).read_bytes()

    return fetch


def _warm_cache(export_tree: Path, cache: Path) -> None:
    source = RemoteSnapshotSource("https://host/tree/", fetch=_reader(export_tree), cache_dir=cache)
    snapshot = Snapshot.load(source)
    snapshot.verify()  # touches every file, populating the cache


def test_cached_root_index_is_disclosed(export_tree, tmp_path):
    cache = tmp_path / "cache"
    _warm_cache(export_tree, cache)
    # All network reads fail; everything must come from cache and be disclosed.
    cold = RemoteSnapshotSource("https://host/tree/", fetch=_reader(export_tree, fail={AGENT_INDEX_FILE}), cache_dir=cache)
    snapshot = Snapshot.load(cold)
    assert snapshot.from_cache is True
    assert snapshot.provenance()["from_cache"] is True


def test_cached_non_root_export_is_disclosed(export_tree, tmp_path):
    cache = tmp_path / "cache"
    _warm_cache(export_tree, cache)
    # Root index served fresh; the vendor export only available from cache.
    cold = RemoteSnapshotSource(
        "https://host/tree/", fetch=_reader(export_tree, fail={"vendors/example-vendor.json"}), cache_dir=cache
    )
    snapshot = Snapshot.load(cold)
    assert snapshot.from_cache is False
    tools.get_vendor(snapshot, "example-vendor")
    assert snapshot.from_cache is True


def test_mixed_fresh_and_cached_but_consistent_verifies_ok(export_tree, tmp_path):
    cache = tmp_path / "cache"
    _warm_cache(export_tree, cache)
    cold = RemoteSnapshotSource(
        "https://host/tree/", fetch=_reader(export_tree, fail={"sources/index.json"}), cache_dir=cache
    )
    snapshot = Snapshot.load(cold)
    report = tools.verify_snapshot(snapshot)["verification"]
    assert report["ok"] is True
    assert report["from_cache"] is True


def test_corrupted_cache_fails_closed(export_tree, tmp_path):
    cache = tmp_path / "cache"
    _warm_cache(export_tree, cache)
    (cache / "vendors" / "example-vendor.json").write_text("{ not json", encoding="utf-8")
    cold = RemoteSnapshotSource(
        "https://host/tree/", fetch=_reader(export_tree, fail={"vendors/example-vendor.json"}), cache_dir=cache
    )
    snapshot = Snapshot.load(cold)
    with pytest.raises(SnapshotError):
        snapshot.vendor_export("example-vendor")


def test_stale_cached_export_against_fresh_index_fails_closed(export_tree, tmp_path):
    cache = tmp_path / "cache"
    _warm_cache(export_tree, cache)
    # Corrupt the cached vendor payload so its digest no longer matches the
    # (fresh) index. Served from cache, it must fail closed.
    cached_vendor = cache / "vendors" / "example-vendor.json"
    doc = json.loads(cached_vendor.read_text(encoding="utf-8"))
    doc["domains"] = ["stale.example"]
    cached_vendor.write_text(json.dumps(doc), encoding="utf-8")
    cold = RemoteSnapshotSource(
        "https://host/tree/", fetch=_reader(export_tree, fail={"vendors/example-vendor.json"}), cache_dir=cache
    )
    snapshot = Snapshot.load(cold)
    with pytest.raises(SnapshotIntegrityError):
        snapshot.vendor_export("example-vendor")


def test_fresh_export_against_cached_older_index_fails_closed(export_tree, tmp_path):
    cache = tmp_path / "cache"
    _warm_cache(export_tree, cache)
    # Make the cached index "older": it lists a stale digest for the vendor
    # export, but remains internally consistent (valid self-digest).
    cached_index = cache / AGENT_INDEX_FILE
    index = json.loads(cached_index.read_text(encoding="utf-8"))
    for entry in index["vendor_exports"]:
        if entry["vendor_id"] == "example-vendor":
            entry["digest"] = "sha256:" + "0" * 64
    index["snapshot"]["digest"] = payload_digest(index)
    cached_index.write_text(json.dumps(index), encoding="utf-8")
    # Root index from cache (older); vendor export served fresh.
    cold = RemoteSnapshotSource("https://host/tree/", fetch=_reader(export_tree, fail={AGENT_INDEX_FILE}), cache_dir=cache)
    snapshot = Snapshot.load(cold)
    with pytest.raises(SnapshotIntegrityError):
        snapshot.vendor_export("example-vendor")


def test_verify_enforces_supported_schema_for_every_export(export_tree):
    target = export_tree / "vendors" / "example-vendor.json"
    doc = json.loads(target.read_text(encoding="utf-8"))
    doc["schema_version"] = "9.9.9"
    target.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    snapshot = Snapshot.load(LocalSnapshotSource(export_tree))
    with pytest.raises(SnapshotUnsupportedSchemaError):
        snapshot.verify()
