"""Release coherence manifest.

Ties one tagged snapshot to the distributions built from it. The manifest keeps
four identities distinct — release tag, repository commit, catalog/export schema
version, and MCP software version — so a reader never conflates the software
package version with the catalog snapshot. It is generated from the *actual*
built asset files (their bytes are hashed), not from a hardcoded filename list,
so it cannot drift from what was published.

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
from tools.openva.agent_export import build_agent_exports
from tools.openva.indexes import EXPORT_SCHEMA_VERSION, ROOT, SCHEMA_VERSION

MANIFEST_SCHEMA_VERSION = "0.1.0"
MCP_PYPROJECT = ROOT / "integrations" / "mcp" / "openva_mcp" / "pyproject.toml"
DEFAULT_MANIFEST_NAME = "openva-release-manifest.json"
DEFAULT_CHECKSUMS_NAME = "SHA256SUMS"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def mcp_software_version() -> str:
    data = tomllib.loads(MCP_PYPROJECT.read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def agent_index_digest(commit_sha: str, generated_at: str, *, out_dir: Path | None = None) -> str:
    """Build the agent export tree and return the root index digest."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        target = out_dir or Path(tmp)
        summary = build_agent_exports(out_dir=target, commit_sha=commit_sha, generated_at=generated_at)
        return str(summary["agent_index_digest"])


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
        if path.is_file() and path.name not in exclude:
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
    agent_digest: str,
    software_version: str | None = None,
) -> dict[str, Any]:
    assets = asset_rows(asset_dir, exclude={DEFAULT_MANIFEST_NAME, DEFAULT_CHECKSUMS_NAME})
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
        "agent_index_digest": agent_digest,
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


def write_checksums(asset_dir: Path, *, exclude: set[str]) -> Path:
    lines = []
    for row in asset_rows(asset_dir, exclude=exclude):
        lines.append(f"{row['sha256'].removeprefix('sha256:')}  {row['name']}")
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
    if not str(manifest.get("agent_index_digest", "")).startswith("sha256:"):
        failures.append("release manifest agent_index_digest must be a sha256 digest")

    # Every listed asset must exist and hash to the recorded digest.
    recorded = {row["name"]: row for row in manifest.get("assets", [])}
    actual = {row["name"]: row for row in asset_rows(asset_dir, exclude={DEFAULT_MANIFEST_NAME, DEFAULT_CHECKSUMS_NAME})}
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
    build.add_argument("--release-tag", default=os.environ.get("GITHUB_REF_NAME", ""))
    build.add_argument("--commit-sha", default=os.environ.get("GITHUB_SHA", ""))
    build.add_argument("--published-at", required=True)
    build.add_argument("--out", type=Path, default=None)

    check = sub.add_parser("check", help="Verify the manifest against the assets on disk")
    check.add_argument("--asset-dir", type=Path, required=True)
    check.add_argument("--manifest", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "build":
        digest = agent_index_digest(args.commit_sha or "unknown", args.published_at)
        write_checksums(args.asset_dir, exclude={DEFAULT_MANIFEST_NAME, DEFAULT_CHECKSUMS_NAME})
        manifest = build_release_manifest(
            asset_dir=args.asset_dir,
            release_tag=args.release_tag,
            commit_sha=args.commit_sha or "unknown",
            published_at=args.published_at,
            agent_digest=digest,
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
