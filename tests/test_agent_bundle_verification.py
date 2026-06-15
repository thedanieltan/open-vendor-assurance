"""Prove the downloadable agent-export ZIP is consumable by the real verifier.

The release attaches openva-agent-exports.zip. These tests build it the same way
the release does (deterministic archive of a real agent-export tree), extract it,
and run the MCP snapshot verifier — the single authority for full-tree
verification — over the extracted bundle. release_coherence only checks the
archive identity/digest/commit; completeness of the tree is proven here.
"""

import sys
import zipfile
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

from openva_mcp.snapshot import LocalSnapshotSource, Snapshot, SnapshotError  # noqa: E402

from tools.openva.agent_export import build_agent_exports  # noqa: E402
from tools.openva.deterministic_zip import build_deterministic_zip  # noqa: E402

COMMIT = "bundletest" + "0" * 30
GENERATED_AT = "2026-06-15T12:00:00Z"


def _make_extracted_bundle(tmp_path: Path, mutate=None) -> Path:
    staging = tmp_path / "staging"
    build_agent_exports(out_dir=staging, commit_sha=COMMIT, generated_at=GENERATED_AT)
    # A mutation can drop a child the root index still lists, producing a valid
    # root index that points at a missing child export.
    if mutate is not None:
        mutate(staging)
    archive = tmp_path / "openva-agent-exports.zip"
    build_deterministic_zip(staging, archive, arcname_root="public", generated_at=GENERATED_AT)
    extract = tmp_path / "extract"
    extract.mkdir()
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(extract)
    return extract  # contains public/...


def _a_vendor_export(staging: Path) -> Path:
    return next(p for p in sorted(staging.glob("vendors/*.json")) if p.name != "index.json")


def test_extracted_bundle_passes_real_verifier(tmp_path):
    extract = _make_extracted_bundle(tmp_path)
    snapshot = Snapshot.load(LocalSnapshotSource(extract))
    report = snapshot.verify()
    assert report["ok"] is True
    assert all(f["match"] for f in report["files"])
    assert report["commit_sha"] == COMMIT


def test_extracted_bundle_missing_index_export_fails(tmp_path):
    # Root index still lists sources/index.json, but the archive lacks it.
    extract = _make_extracted_bundle(tmp_path, mutate=lambda s: (s / "sources" / "index.json").unlink())
    snapshot = Snapshot.load(LocalSnapshotSource(extract))
    with pytest.raises(SnapshotError):
        snapshot.verify()


def test_extracted_bundle_missing_vendor_export_fails(tmp_path):
    extract = _make_extracted_bundle(tmp_path, mutate=lambda s: _a_vendor_export(s).unlink())
    snapshot = Snapshot.load(LocalSnapshotSource(extract))
    with pytest.raises(SnapshotError):
        snapshot.verify()
