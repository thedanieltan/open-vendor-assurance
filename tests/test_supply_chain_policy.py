"""WP-02E deployment-artifact + supply-chain policy tests.

Negative + positive proofs that the release gate fails closed. The gate logic lives in
the service package (openva_match_service.supply_chain) and is exercised here in the
standard suite and by the release-image workflow.

Proves, per the WP-02E acceptance criteria:
  - mutable production image references are rejected;
  - the deployed artifact reference must be a digest;
  - missing SBOM/provenance fails the release gate;
  - unapproved critical/high vulnerability findings fail closed (unknown severity too);
  - documented unexpired exceptions suppress a finding, expired ones do not;
  - the pinned-base policy rejects an unpinned FROM and accepts the real Dockerfile;
  - rollback must target a prior immutable digest;
  - hosted capabilities remain disabled by default;
  - the policy file declares the no-deploy / not-live boundaries (static layer
    unaffected: this slice changes no runtime defaults).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from openva_match_service import supply_chain as sc
from openva_match_service.config import ServiceConfig

ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = ROOT / "services" / "openva_match_service"
DOCKERFILE = SERVICE_ROOT / "Dockerfile"
POLICY = SERVICE_ROOT / "supply-chain-policy.yaml"

_DIGEST = "ghcr.io/example/openva-match-service@sha256:" + "a" * 64
_PINNED_BASE = (
    "python:3.12-slim@sha256:9d3abd9fc11d06998ccdbdd93b4dd49b5ad7d67fcbbc11c016eb0eb2c2194891"
)


def _valid_manifest(**overrides):
    manifest = {
        "image_ref": _DIGEST,
        "dockerfile": f'FROM {_PINNED_BASE}\nENTRYPOINT ["openva-match-service"]\n',
        "sbom": {"bomFormat": "CycloneDX", "components": [{"name": "fastapi", "version": "0.115.0"}]},
        "provenance": {
            "predicateType": "https://slsa.dev/provenance/v1",
            "subject": [{"name": "openva-match-service", "digest": {"sha256": "a" * 64}}],
        },
        "scan": {"findings": [{"id": "CVE-0000-0001", "severity": "low"}]},
    }
    manifest.update(overrides)
    return manifest


def _policy(**vuln):
    base = {"vulnerability_policy": {"fail_on_severity": "high", "exceptions": []}}
    base["vulnerability_policy"].update(vuln)
    return base


# --- immutable digest reference -----------------------------------------------


@pytest.mark.parametrize(
    "ref",
    [
        "openva-match-service:latest",
        "openva-match-service:v1",
        "ghcr.io/example/openva-match-service",  # untagged, unpinned
        "ghcr.io/example/openva-match-service:1.2.3",
        "name@sha256:short",  # malformed digest
        "",
    ],
)
def test_mutable_or_unpinned_reference_is_rejected(ref):
    assert not sc.is_digest_pinned(ref)
    with pytest.raises(sc.SupplyChainViolation):
        sc.assert_immutable_image_ref(ref)


def test_digest_reference_is_accepted():
    assert sc.is_digest_pinned(_DIGEST)
    assert sc.assert_immutable_image_ref(_DIGEST) == _DIGEST


def test_release_rejects_mutable_deploy_reference():
    failures = sc.evaluate_release(_valid_manifest(image_ref="openva-match-service:latest"), _policy())
    assert any("immutable digest" in f for f in failures)


# --- pinned base-image policy -------------------------------------------------


def test_unpinned_from_is_rejected():
    with pytest.raises(sc.SupplyChainViolation):
        sc.assert_dockerfile_base_pinned("FROM python:3.12-slim\n")
    assert sc.unpinned_base_refs("FROM python:3.12-slim\n") == ["python:3.12-slim"]


def test_real_service_dockerfile_base_is_digest_pinned():
    refs = sc.assert_dockerfile_base_pinned(DOCKERFILE.read_text(encoding="utf-8"))
    assert refs and all(sc.is_digest_pinned(r) for r in refs)


def test_policy_pinned_base_matches_dockerfile():
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    dockerfile_bases = set(sc.dockerfile_base_refs(DOCKERFILE.read_text(encoding="utf-8")))
    assert set(policy["pinned_base_images"]) == dockerfile_bases


# --- SBOM + provenance presence -----------------------------------------------


def test_missing_sbom_fails_the_release_gate():
    manifest = _valid_manifest()
    del manifest["sbom"]
    failures = sc.evaluate_release(manifest, _policy())
    assert any("sbom" in f.lower() for f in failures)


def test_empty_sbom_fails_closed():
    with pytest.raises(sc.SupplyChainViolation):
        sc.assert_sbom_present({"components": []})


def test_missing_provenance_fails_the_release_gate():
    manifest = _valid_manifest()
    del manifest["provenance"]
    failures = sc.evaluate_release(manifest, _policy())
    assert any("provenance" in f.lower() for f in failures)


def test_provenance_must_bind_the_artifact_digest():
    with pytest.raises(sc.SupplyChainViolation):
        sc.assert_provenance_present(
            {"predicateType": "x", "subject": [{"digest": {"sha256": "b" * 64}}]},
            artifact_digest="sha256:" + "a" * 64,
        )


# --- vulnerability scan, fail-closed ------------------------------------------


def test_unapproved_critical_finding_fails_closed():
    findings = [{"id": "CVE-2026-9999", "severity": "critical"}]
    with pytest.raises(sc.SupplyChainViolation):
        sc.assert_scan_passes(findings, sc.policy_from_mapping(_policy()))


def test_high_finding_fails_closed_at_default_threshold():
    findings = [{"id": "CVE-2026-1", "severity": "high"}]
    assert not sc.evaluate_scan(findings, sc.policy_from_mapping(_policy())).passed


def test_unknown_severity_blocks_fail_closed():
    findings = [{"id": "CVE-2026-2", "severity": "frobnicated"}]
    assert not sc.evaluate_scan(findings, sc.policy_from_mapping(_policy())).passed


def test_below_threshold_finding_passes():
    findings = [{"id": "CVE-2026-3", "severity": "medium"}]
    assert sc.evaluate_scan(findings, sc.policy_from_mapping(_policy())).passed


def test_documented_unexpired_exception_suppresses_finding():
    findings = [{"id": "CVE-2026-4", "severity": "critical"}]
    policy = _policy(exceptions=[{"id": "CVE-2026-4", "reason": "no fix; not reachable", "expires": "2099-01-01"}])
    decision = sc.evaluate_scan(findings, sc.policy_from_mapping(policy), on=date(2026, 6, 23))
    assert decision.passed and len(decision.exempted) == 1


def test_expired_exception_does_not_suppress_finding():
    findings = [{"id": "CVE-2026-5", "severity": "critical"}]
    policy = _policy(exceptions=[{"id": "CVE-2026-5", "reason": "stale", "expires": "2025-01-01"}])
    decision = sc.evaluate_scan(findings, sc.policy_from_mapping(policy), on=date(2026, 6, 23))
    assert not decision.passed and decision.expired_exceptions == ["CVE-2026-5"]


def test_trivy_and_grype_report_shapes_are_parsed():
    trivy = {"Results": [{"Vulnerabilities": [{"VulnerabilityID": "CVE-1", "Severity": "CRITICAL"}]}]}
    grype = {"matches": [{"vulnerability": {"id": "CVE-2", "severity": "High"}}]}
    assert {f["id"] for f in sc._scan_findings(trivy)} == {"CVE-1"}
    assert {f["id"] for f in sc._scan_findings(grype)} == {"CVE-2"}


# --- rollback by prior digest -------------------------------------------------


def test_rollback_target_must_be_a_digest():
    with pytest.raises(sc.SupplyChainViolation):
        sc.assert_rollback_target("openva-match-service:previous")
    assert sc.assert_rollback_target(_DIGEST) == _DIGEST


def test_release_rejects_mutable_rollback_ref():
    failures = sc.evaluate_release(_valid_manifest(rollback_ref="svc:prev"), _policy())
    assert any("rollback" in f.lower() for f in failures)


# --- composite happy path -----------------------------------------------------


def test_fully_valid_release_passes_every_gate():
    assert sc.evaluate_release(_valid_manifest(rollback_ref=_DIGEST), _policy()) == []


# --- posture: hosted capabilities off by default; static layer unaffected -----


def test_hosted_capabilities_remain_disabled_by_default():
    cfg = ServiceConfig(pack_path=Path("/data/openva-pack"), api_key="k")
    assert cfg.verify_transport_enabled is False
    assert cfg.candidate_ingress_enabled is False
    assert cfg.public_read_enabled is False
    assert cfg.verify_kill_switch is False


def test_policy_declares_no_deploy_and_not_live_boundaries():
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    b = policy["boundaries"]
    assert b["deployment"] is False
    assert b["hosted_endpoint_live"] is False
    assert b["registry_creation"] is False
    assert b["cloud_provisioning"] is False
    assert b["paid_publication"] is False
