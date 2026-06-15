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


def test_tampered_source_index_fails_closed(export_tree):
    target = export_tree / "sources" / "index.json"
    doc = json.loads(target.read_text(encoding="utf-8"))
    doc["sources"].append({"vendor_id": "x", "source_id": "injected", "source_url": "https://evil.example"})
    target.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    snapshot = Snapshot.load(LocalSnapshotSource(export_tree))
    with pytest.raises(SnapshotIntegrityError):
        snapshot.sources_index()


def test_local_and_hosted_modes_agree_on_ids_urls_and_snapshot(export_tree):
    local = Snapshot.load(LocalSnapshotSource(export_tree))
    hosted = Snapshot.load(RemoteSnapshotSource("https://host/tree/", fetch=_reader(export_tree)))

    # Same snapshot identity regardless of transport.
    assert local.commit_sha == hosted.commit_sha
    assert local.digest == hosted.digest

    local_v = tools.get_vendor(local, "example-vendor")["vendor"]
    hosted_v = tools.get_vendor(hosted, "example-vendor")["vendor"]
    assert local_v["vendor_id"] == hosted_v["vendor_id"]
    assert [s["source_url"] for s in local_v["sources"]] == [s["source_url"] for s in hosted_v["sources"]]


def _rewrite_index(export_tree: Path, mutate) -> None:
    """Apply a mutation to the root index and refresh its self-digest, so the
    self-digest check passes and root-index *structure* validation is exercised.
    """
    target = export_tree / AGENT_INDEX_FILE
    doc = json.loads(target.read_text(encoding="utf-8"))
    mutate(doc)
    doc["snapshot"]["digest"] = payload_digest(doc)
    target.write_text(json.dumps(doc), encoding="utf-8")


def _drop_export(doc):
    del doc["exports"]["vendors_index"]


def _wrong_path(doc):
    doc["exports"]["sources_index"]["path"] = "sources/wrong.json"


def _bad_digest(doc):
    doc["exports"]["changes_latest"]["digest"] = "not-a-digest"


def _duplicate_vendor(doc):
    doc["vendor_exports"].append(dict(doc["vendor_exports"][0]))


def _path_not_matching_id(doc):
    entry = dict(doc["vendor_exports"][0])
    entry["vendor_id"] = "other-vendor"
    doc["vendor_exports"].append(entry)


@pytest.mark.parametrize("mutate", [_drop_export, _wrong_path, _bad_digest, _duplicate_vendor, _path_not_matching_id])
def test_malformed_root_index_fails_closed(export_tree, mutate):
    _rewrite_index(export_tree, mutate)
    with pytest.raises(SnapshotIntegrityError):
        Snapshot.load(LocalSnapshotSource(export_tree))


def test_unlisted_required_export_with_valid_self_digest_is_rejected(export_tree):
    # Remove a vendor from the root index but leave its (valid) file on disk;
    # loading it must fail because it is not linked from the index.
    _rewrite_index(export_tree, lambda doc: doc["vendor_exports"].clear())
    snapshot = Snapshot.load(LocalSnapshotSource(export_tree))
    with pytest.raises(SnapshotIntegrityError):
        snapshot.load_verified("vendors/example-vendor.json")


def _mutate_child_snapshot(path: Path, **changes) -> None:
    """Change a child export's snapshot metadata while leaving its payload (and
    therefore its payload digest) untouched — the exact attack the root binding
    must catch.
    """
    doc = json.loads(path.read_text(encoding="utf-8"))
    for key, value in changes.items():
        if value is _DELETE:
            doc["snapshot"].pop(key, None)
        else:
            doc["snapshot"][key] = value
    path.write_text(json.dumps(doc), encoding="utf-8")


_DELETE = object()


@pytest.mark.parametrize(
    "changes",
    [
        {"commit_sha": "different" + "0" * 32},
        {"generated_at": "2099-01-01T00:00:00Z"},
        {"commit_sha": _DELETE},
        {"generated_at": _DELETE},
    ],
)
def test_child_export_unbound_from_root_fails_closed_local(export_tree, changes):
    _mutate_child_snapshot(export_tree / "vendors" / "index.json", **changes)
    snapshot = Snapshot.load(LocalSnapshotSource(export_tree))
    with pytest.raises(SnapshotIntegrityError):
        snapshot.vendors_index()


def test_child_export_unbound_from_root_fails_closed_hosted(export_tree):
    # Same payload and digest, different child commit: must fail in hosted mode.
    _mutate_child_snapshot(export_tree / "vendors" / "example-vendor.json", commit_sha="other" + "0" * 35)
    snapshot = Snapshot.load(RemoteSnapshotSource("https://host/tree/", fetch=_reader(export_tree)))
    with pytest.raises(SnapshotIntegrityError):
        snapshot.vendor_export("example-vendor")


def test_cached_child_from_older_snapshot_fails_closed(export_tree, tmp_path):
    cache = tmp_path / "cache"
    _warm_cache(export_tree, cache)
    # Replace the cached child with an older-snapshot copy: identical payload,
    # different commit_sha. Served from cache, the root binding must reject it.
    cached_child = cache / "vendors" / "example-vendor.json"
    _mutate_child_snapshot(cached_child, commit_sha="older" + "0" * 35)
    cold = RemoteSnapshotSource(
        "https://host/tree/", fetch=_reader(export_tree, fail={"vendors/example-vendor.json"}), cache_dir=cache
    )
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
