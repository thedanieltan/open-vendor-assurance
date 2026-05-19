from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from tools.openva.conformance import validate_pack_dir
from tools.openva.indexes import EXPORT_PROFILE_ID, EXPORT_SCHEMA_VERSION, ROOT, SCHEMA_VERSION
from tools.openva.pack import verify_pack_integrity
from tools.openva.release_artifacts import build_manifest
from tools.openva.validate import validate_all

REQUIRED_RELEASE_DOCS = [
    "README.md",
    "DISCLAIMER.md",
    "CONTRIBUTING.md",
    "GOVERNANCE.md",
    "MAINTAINERS.md",
    "SECURITY.md",
    "docs/index.md",
    "docs/versioning-policy.md",
    "docs/release-policy.md",
    "docs/release-checklist.md",
    "docs/v0.1.0-release-candidate.md",
    "docs/public-launch-cutover.md",
    "docs/ci-and-branch-protection.md",
    "docs/consumer-conformance-fixtures.md",
]

REQUIRED_RELEASE_COMMANDS = [
    "python -m tools.openva.release_artifacts build",
    "python -m tools.openva.validate build-indexes",
    "python -m tools.openva.validate validate",
    "pytest -q",
    "python -m tools.openva.conformance fixtures/packs/minimal-valid",
    "python -m tools.openva.conformance fixtures/packs/valid-bot-protected-observation",
]

VALID_FIXTURE_PACKS = [
    ROOT / "fixtures/packs/minimal-valid",
    ROOT / "fixtures/packs/valid-bot-protected-observation",
    ROOT / "fixtures/packs/valid-brand-only-fallback",
]

REQUIRED_LIMITATION_PHRASES = [
    "public-source-only",
    "metadata-first",
    "does not provide legal",
    "vendor-risk advice",
    "private or gated",
    "customer-specific",
    "raw vendor documents",
]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def check_docs_exist() -> list[str]:
    failures: list[str] = []
    for rel_path in REQUIRED_RELEASE_DOCS:
        if not (ROOT / rel_path).is_file():
            failures.append(f"{rel_path}: required release document is missing")
    return failures


def check_pack_identifiers() -> list[str]:
    failures: list[str] = []
    pack = load_json(ROOT / "openva-pack.json")
    expected = {
        "profileId": EXPORT_PROFILE_ID,
        "schemaVersion": EXPORT_SCHEMA_VERSION,
        "packId": "open-vendor-assurance",
        "schema_version": SCHEMA_VERSION,
        "pack_id": "open-vendor-assurance",
    }
    for key, value in expected.items():
        if pack.get(key) != value:
            failures.append(f"openva-pack.json: {key} must be {value}")

    guarantees = pack.get("guarantees", {})
    for key in ["public_sources_only", "metadata_first", "non_advisory"]:
        if guarantees.get(key) is not True:
            failures.append(f"openva-pack.json: guarantee {key} must be true")
    if guarantees.get("raw_documents_mirrored_by_default") is not False:
        failures.append("openva-pack.json: raw_documents_mirrored_by_default must be false")
    return failures


def check_release_docs() -> list[str]:
    failures: list[str] = []
    combined = "\n".join(text(path) for path in REQUIRED_RELEASE_DOCS if (ROOT / path).exists())
    lower = combined.lower()

    for command in REQUIRED_RELEASE_COMMANDS:
        if command not in combined:
            failures.append(f"release docs: missing required command `{command}`")

    for phrase in REQUIRED_LIMITATION_PHRASES:
        if phrase not in lower:
            failures.append(f"release docs: missing limitation phrase `{phrase}`")

    for identifier in [EXPORT_PROFILE_ID, EXPORT_SCHEMA_VERSION, SCHEMA_VERSION, "v0.1.0"]:
        if identifier not in combined:
            failures.append(f"release docs: missing release identifier `{identifier}`")

    return failures


def check_conformance_fixtures() -> list[str]:
    failures: list[str] = []
    for fixture in VALID_FIXTURE_PACKS:
        failures.extend(validate_pack_dir(fixture))
    return failures


def check_release_artifact_manifest_builds() -> list[str]:
    manifest = build_manifest()
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return ["release artifact manifest must contain at least one artifact"]
    for artifact in artifacts:
        if not str(artifact.get("sha256", "")).startswith("sha256:"):
            return [f"release artifact {artifact.get('path', '<unknown>')} is missing sha256"]
        if not isinstance(artifact.get("size_bytes"), int) or artifact["size_bytes"] <= 0:
            return [f"release artifact {artifact.get('path', '<unknown>')} must have positive size_bytes"]
    return []


def check_git_generated_diff() -> list[str]:
    command = ["git", "diff", "--exit-code", "openva-pack.json", "indexes/", "dist/"]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    if result.returncode == 0:
        return []
    details = result.stdout.strip() or result.stderr.strip()
    if details:
        return ["generated pack/index files changed after build-indexes:\n" + details]
    return ["generated pack/index files changed after build-indexes"]


def run_release_smoke(*, check_git_diff: bool = True) -> list[str]:
    failures: list[str] = []
    failures.extend(check_docs_exist())
    failures.extend(check_pack_identifiers())
    failures.extend(check_release_docs())
    failures.extend(verify_pack_integrity())
    failures.extend(check_conformance_fixtures())
    failures.extend(check_release_artifact_manifest_builds())

    validation_status = validate_all()
    if validation_status != 0:
        failures.append("python -m tools.openva.validate validate failed")

    if check_git_diff:
        failures.extend(check_git_generated_diff())

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-release-smoke")
    parser.add_argument(
        "--skip-git-diff",
        action="store_true",
        help="Skip the git diff check for generated pack/index files. Intended for unit tests only.",
    )
    args = parser.parse_args()

    failures = run_release_smoke(check_git_diff=not args.skip_git_diff)
    if failures:
        for failure in failures:
            print(failure)
        print(f"Release smoke test failed: {len(failures)} issue(s).")
        return 1

    print("Release smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
