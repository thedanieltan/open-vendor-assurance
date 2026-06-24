"""Workflow-contract tests for .github/workflows/release-image.yml (WP-02E).

Pin the supply-chain-critical properties of the release-image workflow so they cannot
silently regress: read-only + manual-only, OCI manifest-digest derivation (not the local
config .Id), fail-closed scanning (no `|| true`), digest-to-digest reproducibility,
pinned scanner tooling, the authoritative gate running last over the accepted-release
ledger, and no push/registry/deploy/live surface.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/release-image.yml")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _workflow() -> dict:
    return yaml.safe_load(_text())


def _triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def test_manual_only_and_read_only():
    workflow = _workflow()
    assert set(_triggers(workflow).keys()) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read", "actions": "read"}


def test_derives_oci_manifest_digest_not_config_id():
    text = _text()
    assert "type=oci" in text
    assert '"containerimage.digest"' in text
    # The withdrawn local-config-id derivation must not reappear.
    assert ".Id" not in text
    assert "docker image inspect" not in text


def test_scanning_is_fail_closed():
    text = _text()
    assert "|| true" not in text
    assert "test -s scan.image.json" in text
    assert "test -s scan.fs.json" in text
    assert "--input image.oci.tar" in text  # image scan runs on the built OCI archive


def test_reproducibility_is_digest_to_digest():
    text = _text()
    assert "rebuild-metadata.json" in text
    assert "REBUILD_DIGEST" in text
    assert "reproducibility-report.json" in text


def test_supply_chain_tools_are_pinned_and_checksum_verified():
    text = _text()
    env = _workflow().get("env", {})
    # Pinned versioned release archives + reviewed-literal checksums in env.
    for key in ("SYFT_VERSION", "SYFT_URL", "SYFT_SHA256", "TRIVY_VERSION", "TRIVY_URL", "TRIVY_SHA256"):
        assert env.get(key), f"missing pinned tool env {key}"
    # The archives are verified before execution.
    assert "sha256sum -c -" in text


def test_no_mutable_installer_bootstrap():
    text = _text()
    # The prior fail-open bootstrap (mutable `main` installer piped into a shell) must not reappear.
    for forbidden in (
        "raw.githubusercontent.com/anchore/syft/main/install.sh",
        "raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh",
        "| sh -s --",
    ):
        assert forbidden not in text
    assert "/main/" not in text  # no mutable-branch dependency anywhere


def test_authoritative_gate_runs_after_all_evidence_and_uses_ledger():
    text = _text()
    gate = text.index("check-release")
    assert text.index("reproducibility-report.json") < gate
    assert text.index("sbom.cyclonedx.json") < gate
    assert text.index("provenance.intoto.json") < gate
    assert "--accepted-releases" in text


def test_no_push_registry_deploy_or_live_surface():
    low = _text().lower()
    # Real push / registry-output / write indicators (the word "registry" appears only in
    # the "no registry" boundary comments, so we forbid the push mechanisms, not the word).
    for forbidden in ("docker push", "git push", "gh release create", "contents: write", "--push", "type=registry"):
        assert forbidden not in low


def test_evidence_is_retained_90_days():
    text = _text()
    assert "retention-days: 90" in text
    assert "actions/upload-artifact@v6" in text


def test_uses_node24_compatible_actions():
    text = _text()
    for stale in ("actions/checkout@v4", "actions/setup-python@v5", "actions/upload-artifact@v4"):
        assert stale not in text
