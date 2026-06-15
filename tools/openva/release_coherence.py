"""Release coherence manifest.

Ties one tagged snapshot to the distributions built from it. The manifest keeps
four identities distinct — release tag, repository commit, catalog/export schema
version, and MCP software version — so a reader never conflates the software
package version with the catalog snapshot. It is generated from the *actual*
built asset files (their bytes are hashed), not from a hardcoded filename list,
so it cannot drift from what was published.

The agent-index digest is read from the agent-export bundle that is actually
attached to the release (`agent-exports/public/openva-agent-index.json`), and
its declared digest is recomputed from those bytes. The release commit must
match the export snapshot commit. This immutable release export is distinct from
the hosted site export, which may carry fresher observation input.

It records only identities and digests. It makes no claim that any artifact was
published to PyPI, an OCI registry, or the MCP Registry, and adds no signing or
provenance attestation the workflow does not actually emit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tomllib
from pathlib import Path
from typing import Any

from tools.openva.agent_export import SCHEMA_VERSION as AGENT_EXPORT_SCHEMA_VERSION
from tools.openva.agent_export import payload_digest
from tools.openva.indexes import EXPORT_SCHEMA_VERSION, ROOT, SCHEMA_VERSION

MANIFEST_SCHEMA_VERSION = "0.1.0"
MCP_PYPROJECT = ROOT / "integrations" / "mcp" / "openva_mcp" / "pyproject.toml"
DEFAULT_MANIFEST_NAME = "openva-release-manifest.json"
DEFAULT_CHECKSUMS_NAME = "SHA256SUMS"
AGENT_INDEX_IN_ARCHIVE = "public/openva-agent-index.json"
SELF_EXCLUDE = {DEFAULT_MANIFEST_NAME, DEFAULT_CHECKSUMS_NAME}
# The agent-export tree is staged here only to be zipped; the zip is the release
# asset, so the loose tree is not listed as a separate asset.
STAGING_DIRS = {"agent-exports"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def mcp_software_version() -> str:
    data = tomllib.loads(MCP_PYPROJECT.read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def read_release_agent_index(agent_index_path: Path) -> dict[str, Any]:
    """Read the staged agent index and recompute its digest from the bytes.

    Fails if the declared digest does not recompute, so the manifest never
    records a digest that is not provable from the attached file.
    """
    document = json.loads(agent_index_path.read_text(encoding="utf-8"))
    snapshot = document.get("snapshot", {})
    declared = str(snapshot.get("digest", ""))
    recomputed = payload_digest(document)
    if declared != recomputed:
        raise ValueError(
            f"{agent_index_path}: agent index digest does not recompute (declared {declared}, got {recomputed})"
        )
    return {
        "digest": recomputed,
        "observation_input": document.get("observation_input"),
        "commit_sha": str(snapshot.get("commit_sha", "")),
        "generated_at": str(snapshot.get("generated_at", "")),
    }


def build_provenance() -> dict[str, Any]:
    # GitHub-supplied identity only; absent locally. No signing/attestation is
    # claimed because the workflow does not emit one.
    return {
        "repository": os.environ.get("GITHUB_REPOSITORY"),
        "workflow": os.environ.get("GITHUB_WORKFLOW"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "ref": os.environ.get("GITHUB_REF"),
        "signed": False,
        "attested": False,
    }


def asset_rows(asset_dir: Path, *, exclude: set[str]) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(asset_dir.rglob("*")):
        rel_parts = path.relative_to(asset_dir).parts
        if path.is_file() and path.name not in exclude and rel_parts[0] not in STAGING_DIRS:
            rows.append(
                {
                    "name": path.relative_to(asset_dir).as_posix(),
                    "sha256": sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
            )
    return rows


def build_release_manifest(
    *,
    asset_dir: Path,
    release_tag: str,
    commit_sha: str,
    published_at: str,
    agent_index_path: Path,
    agent_archive_name: str,
    software_version: str | None = None,
) -> dict[str, Any]:
    agent = read_release_agent_index(agent_index_path)
    if commit_sha and agent["commit_sha"] and agent["commit_sha"] != commit_sha:
        raise ValueError(
            f"release commit {commit_sha} does not match export snapshot commit {agent['commit_sha']}"
        )
    assets = asset_rows(asset_dir, exclude=SELF_EXCLUDE)
    return {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "not_advice": True,
        # Four distinct identities — never collapse software version into the
        # catalog snapshot.
        "identities": {
            "release_tag": release_tag,
            "repository_commit_sha": commit_sha,
            "catalog_record_schema_version": SCHEMA_VERSION,
            "export_pack_schema_version": EXPORT_SCHEMA_VERSION,
            "agent_export_schema_version": AGENT_EXPORT_SCHEMA_VERSION,
            "mcp_software_version": software_version or mcp_software_version(),
        },
        # The immutable agent-export release bundle (distinct from the hosted
        # site export, which may carry fresher observation input).
        "agent_export": {
            "archive_asset": agent_archive_name,
            "index_path_in_archive": AGENT_INDEX_IN_ARCHIVE,
            "index_digest": agent["digest"],
            "observation_input": agent["observation_input"],
            "snapshot_commit_sha": agent["commit_sha"],
        },
        "agent_index_digest": agent["digest"],
        "published_at": published_at,
        "build_provenance": build_provenance(),
        "distributions": {
            "pypi_published": False,
            "oci_published": False,
            "mcp_registry_published": False,
        },
        "asset_count": len(assets),
        "assets": assets,
    }


def write_checksums(asset_dir: Path, *, exclude: set[str] = SELF_EXCLUDE) -> Path:
    lines = [f"{row['sha256'].removeprefix('sha256:')}  {row['name']}" for row in asset_rows(asset_dir, exclude=exclude)]
    path = asset_dir / DEFAULT_CHECKSUMS_NAME
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def check_release_manifest(asset_dir: Path, manifest_path: Path) -> list[str]:
    failures: list[str] = []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    required_identities = {
        "release_tag",
        "repository_commit_sha",
        "catalog_record_schema_version",
        "export_pack_schema_version",
        "agent_export_schema_version",
        "mcp_software_version",
    }
    identities = manifest.get("identities", {})
    missing = sorted(required_identities - set(identities))
    if missing:
        failures.append(f"release manifest missing identities: {missing}")
    if manifest.get("not_advice") is not True:
        failures.append("release manifest must assert not_advice=true")

    agent = manifest.get("agent_export", {})
    for field in ("archive_asset", "index_path_in_archive", "index_digest", "observation_input", "snapshot_commit_sha"):
        if field not in agent:
            failures.append(f"release manifest agent_export missing {field}")
    if not str(manifest.get("agent_index_digest", "")).startswith("sha256:"):
        failures.append("release manifest agent_index_digest must be a sha256 digest")
    # The agent-export archive named in the manifest must be a real asset.
    recorded = {row["name"]: row for row in manifest.get("assets", [])}
    if agent.get("archive_asset") and agent["archive_asset"] not in recorded:
        failures.append(f"agent export archive not among release assets: {agent.get('archive_asset')}")

    actual = {row["name"]: row for row in asset_rows(asset_dir, exclude=SELF_EXCLUDE)}
    for name, row in recorded.items():
        if name not in actual:
            failures.append(f"release asset missing on disk: {name}")
        elif actual[name]["sha256"] != row["sha256"]:
            failures.append(f"release asset digest mismatch: {name}")
    for name in actual:
        if name not in recorded:
            failures.append(f"release asset not recorded in manifest: {name}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-release-coherence")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="Build the release coherence manifest from built assets")
    build.add_argument("--asset-dir", type=Path, required=True)
    build.add_argument("--agent-index", type=Path, required=True, help="Staged agent index JSON inside the asset tree")
    build.add_argument("--agent-archive", required=True, help="Release asset name of the agent-export archive")
    build.add_argument("--release-tag", default=os.environ.get("GITHUB_REF_NAME", ""))
    build.add_argument("--commit-sha", default=os.environ.get("GITHUB_SHA", ""))
    build.add_argument("--published-at", required=True)
    build.add_argument("--out", type=Path, default=None)

    check = sub.add_parser("check", help="Verify the manifest against the assets on disk")
    check.add_argument("--asset-dir", type=Path, required=True)
    check.add_argument("--manifest", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "build":
        write_checksums(args.asset_dir)
        manifest = build_release_manifest(
            asset_dir=args.asset_dir,
            release_tag=args.release_tag,
            commit_sha=args.commit_sha or "unknown",
            published_at=args.published_at,
            agent_index_path=args.agent_index,
            agent_archive_name=args.agent_archive,
        )
        out = args.out or (args.asset_dir / DEFAULT_MANIFEST_NAME)
        out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Built {out}")
        return 0

    failures = check_release_manifest(args.asset_dir, args.manifest)
    if failures:
        for failure in failures:
            print(failure)
        return 1
    print("Release coherence manifest is consistent with assets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
