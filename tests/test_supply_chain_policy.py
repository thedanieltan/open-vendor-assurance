"""WP-02E deployment-artifact + supply-chain policy tests.

Negative + positive proofs that the release gate fails closed, including the
independent-review remediations (fail-closed scanner evidence, unknown-severity always
blocks, mandatory exception expiry, gate consumes its own policy, OCI-manifest-digest
reproducibility, accepted-ledger rollback). The gate logic lives in the service package
(openva_match_service.supply_chain) and is exercised here in the standard suite and by
the release-image workflow.
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
LEDGER = SERVICE_ROOT / "accepted-releases.yaml"

_HEX = "a" * 64
_DIGEST = f"ghcr.io/example/openva-match-service@sha256:{_HEX}"
_BARE = f"sha256:{_HEX}"
_PINNED_BASE = (
    "python:3.12-slim@sha256:9d3abd9fc11d06998ccdbdd93b4dd49b5ad7d67fcbbc11c016eb0eb2c2194891"
)

_TOOLS_POLICY = {
    "syft": {"version": "v1.18.1", "binary": "syft", "archive_url": "https://x", "archive_sha256": "0" * 64},
    "trivy": {"version": "v0.71.2", "binary": "trivy", "archive_url": "https://y", "archive_sha256": "1" * 64},
}
_TOOLS_EVIDENCE = {
    "syft": {"version": "v1.18.1", "archive_sha256": "0" * 64},
    "trivy": {"version": "v0.71.2", "archive_sha256": "1" * 64},
}


_BASE_DIGEST = "sha256:" + "e" * 64


def _trivy_report(vulns=()):
    return {"SchemaVersion": 2, "Results": [{"Target": "debian", "Vulnerabilities": list(vulns)}]}


def _vuln(cve, pkg, version, severity, status="affected", fixed=""):
    return {
        "VulnerabilityID": cve, "PkgName": pkg, "InstalledVersion": version,
        "Severity": severity, "Status": status, "FixedVersion": fixed,
    }


def _base_baseline(entries=(), digest=_BASE_DIGEST, valid_until="2099-01-01"):
    return sc.load_base_baseline({
        "base_image": {"ref": "python:3.12-slim-bookworm@" + digest, "digest": digest, "valid_until": valid_until},
        "accepted_inherited_findings": list(entries),
    })


def _repro(**overrides):
    report = {
        "manifest_digest": _BARE,
        "rebuild_manifest_digest": _BARE,
        "digests_match": True,
        "equivalent": True,
        "package_count": 5,
        "rebuild_package_count": 5,
    }
    report.update(overrides)
    return report


def _valid_manifest(**overrides):
    manifest = {
        "image_ref": _DIGEST,
        "dockerfile": f'FROM {_PINNED_BASE}\nENTRYPOINT ["openva-match-service"]\n',
        "sbom": {"bomFormat": "CycloneDX", "components": [{"name": "fastapi", "version": "0.115.0"}]},
        "provenance": {
            "predicateType": "https://slsa.dev/provenance/v1",
            "subject": [{"name": "openva-match-service", "digest": {"sha256": _HEX}}],
        },
        # No HIGH/CRITICAL by default -> the base-attribution gate passes cleanly.
        "image_scan": _trivy_report([_vuln("CVE-0000-1", "libx", "1", "LOW")]),
        "base_scan": _trivy_report([]),
        "base_image": {"ref": "python:3.12-slim-bookworm@" + _BASE_DIGEST, "digest": _BASE_DIGEST},
        "reproducibility": _repro(),
        "tools": {k: dict(v) for k, v in _TOOLS_EVIDENCE.items()},
    }
    manifest.update(overrides)
    return manifest


def _policy(**vuln):
    vp = {"fail_on_severity": "high", "exceptions": []}
    vp.update(vuln)
    return {
        "pinned_base_images": [_PINNED_BASE],
        "supply_chain_tools": {k: dict(v) for k, v in _TOOLS_POLICY.items()},
        "require": {
            "sbom": True,
            "provenance": True,
            "vulnerability_scan": True,
            "reproducibility_evidence": True,
        },
        "vulnerability_policy": vp,
    }


# --- immutable digest reference -----------------------------------------------


@pytest.mark.parametrize(
    "ref",
    [
        "openva-match-service:latest",
        "openva-match-service:v1",
        "ghcr.io/example/openva-match-service",
        "ghcr.io/example/openva-match-service:1.2.3",
        "name@sha256:short",
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
    assert sc.manifest_digest_of(_DIGEST) == _BARE


def test_release_rejects_mutable_deploy_reference():
    failures = sc.evaluate_release(_valid_manifest(image_ref="openva-match-service:latest"), _policy())
    assert any("immutable digest" in f for f in failures)


# --- pinned base-image policy -------------------------------------------------


def test_unpinned_from_is_rejected():
    with pytest.raises(sc.SupplyChainViolation):
        sc.assert_dockerfile_base_pinned("FROM python:3.12-slim\n")
    assert sc.unpinned_base_refs("FROM python:3.12-slim\n") == ["python:3.12-slim"]


def test_pinned_but_unapproved_base_is_rejected():
    other = "python:3.12-slim@sha256:" + ("b" * 64)
    with pytest.raises(sc.SupplyChainViolation):
        sc.assert_dockerfile_base_pinned(f"FROM {other}\n", allowed_bases=[_PINNED_BASE])


def test_real_service_dockerfile_base_is_digest_pinned_and_approved():
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    refs = sc.assert_dockerfile_base_pinned(
        DOCKERFILE.read_text(encoding="utf-8"), allowed_bases=policy["pinned_base_images"]
    )
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
            artifact_digest=_BARE,
        )


# --- scanner evidence is fail-closed (finding 1) ------------------------------


@pytest.mark.parametrize("scan", [{}, {"SchemaVersion": 2}, {"Results": None}, {"matches": "x"}, "not-an-object"])
def test_missing_or_malformed_scan_evidence_fails_closed(scan):
    with pytest.raises(sc.SupplyChainViolation):
        sc.assert_scan_evidence(scan)


def test_recognised_empty_scan_is_allowed():
    sc.assert_scan_evidence({"Results": []})  # a real successful scan with no findings


def test_release_rejects_unrecognised_image_scan_envelope():
    failures = sc.evaluate_release(_valid_manifest(image_scan={}), _policy())
    assert any("scan" in f.lower() for f in failures)


def test_missing_image_or_base_scan_fails_the_release_gate():
    manifest = _valid_manifest()
    del manifest["image_scan"]
    del manifest["base_scan"]
    failures = sc.evaluate_release(manifest, _policy())
    assert any("image_scan" in f or "base_scan" in f for f in failures)


# --- vulnerability policy, fail-closed ----------------------------------------


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


def test_unknown_severity_cannot_be_exempted_by_an_active_exception():
    # Finding 2: an active exception must NOT suppress an unknown-severity finding.
    findings = [{"id": "CVE-2026-2", "severity": "frobnicated"}]
    policy = _policy(exceptions=[{"id": "CVE-2026-2", "reason": "n/a", "expires": "2099-01-01"}])
    decision = sc.evaluate_scan(findings, sc.policy_from_mapping(policy), on=date(2026, 6, 23))
    assert not decision.passed and decision.exempted == []


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


# --- exceptions require expiry + uniqueness (finding 3) -----------------------


def test_exception_without_expiry_is_rejected():
    with pytest.raises(sc.SupplyChainViolation):
        sc.policy_from_mapping(_policy(exceptions=[{"id": "CVE-1", "reason": "x"}]))


def test_exception_with_invalid_expiry_is_rejected():
    with pytest.raises(sc.SupplyChainViolation):
        sc.policy_from_mapping(_policy(exceptions=[{"id": "CVE-1", "reason": "x", "expires": "soon"}]))


def test_duplicate_exception_ids_are_rejected():
    dupes = [
        {"id": "CVE-1", "reason": "a", "expires": "2099-01-01"},
        {"id": "CVE-1", "reason": "b", "expires": "2099-01-01"},
    ]
    with pytest.raises(sc.SupplyChainViolation):
        sc.policy_from_mapping(_policy(exceptions=dupes))


def test_trivy_and_grype_report_shapes_are_parsed():
    trivy = {"Results": [{"Vulnerabilities": [{"VulnerabilityID": "CVE-1", "Severity": "CRITICAL"}]}]}
    grype = {"matches": [{"vulnerability": {"id": "CVE-2", "severity": "High"}}]}
    assert {f["id"] for f in sc._scan_findings(trivy)} == {"CVE-1"}
    assert {f["id"] for f in sc._scan_findings(grype)} == {"CVE-2"}


# --- reproducibility evidence (findings 4 + 8) --------------------------------


def test_missing_reproducibility_fails_the_release_gate():
    manifest = _valid_manifest()
    del manifest["reproducibility"]
    failures = sc.evaluate_release(manifest, _policy())
    assert any("reproducibility" in f.lower() for f in failures)


def test_reproducibility_requires_matching_oci_manifest_digests():
    with pytest.raises(sc.SupplyChainViolation):
        sc.assert_reproducibility_evidence(_repro(rebuild_manifest_digest="sha256:" + "b" * 64, digests_match=False))


def test_reproducibility_rejects_non_equivalent_package_sets():
    with pytest.raises(sc.SupplyChainViolation):
        sc.assert_reproducibility_evidence(_repro(equivalent=False))


def test_reproducibility_rejects_zero_or_mismatched_counts():
    with pytest.raises(sc.SupplyChainViolation):
        sc.assert_reproducibility_evidence(_repro(package_count=0, rebuild_package_count=0))
    with pytest.raises(sc.SupplyChainViolation):
        sc.assert_reproducibility_evidence(_repro(rebuild_package_count=4))


def test_reproducibility_must_describe_the_deployed_digest():
    other = _repro(manifest_digest="sha256:" + "c" * 64, rebuild_manifest_digest="sha256:" + "c" * 64)
    with pytest.raises(sc.SupplyChainViolation):
        sc.assert_reproducibility_evidence(other, artifact_digest=_BARE)


def test_valid_reproducibility_passes():
    sc.assert_reproducibility_evidence(_repro(), artifact_digest=_BARE)


# --- rollback by ACCEPTED ledger (finding 7) ----------------------------------


def test_rollback_requires_digest_syntax():
    with pytest.raises(sc.SupplyChainViolation):
        sc.assert_rollback_target("openva-match-service:previous", {_BARE})


def test_well_formed_digest_not_in_ledger_is_rejected():
    with pytest.raises(sc.SupplyChainViolation):
        sc.assert_rollback_target(_DIGEST, accepted_digests=set())
    with pytest.raises(sc.SupplyChainViolation):
        sc.assert_rollback_target(_DIGEST, accepted_digests=None)


def test_accepted_digest_rollback_passes():
    assert sc.assert_rollback_target(_DIGEST, accepted_digests={_BARE}) == _DIGEST


def test_release_rejects_rollback_to_unaccepted_digest():
    failures = sc.evaluate_release(_valid_manifest(rollback_ref=_DIGEST), _policy(), accepted_digests=set())
    assert any("accepted" in f.lower() for f in failures)


def test_committed_ledger_is_empty_so_rollback_fails_closed():
    ledger = yaml.safe_load(LEDGER.read_text(encoding="utf-8"))
    assert sc.load_accepted_digests(ledger) == set()


# --- composite happy path -----------------------------------------------------


def test_fully_valid_release_passes_every_gate():
    assert sc.evaluate_release(_valid_manifest(), _policy()) == []


def test_fully_valid_release_with_accepted_rollback_passes():
    manifest = _valid_manifest(rollback_ref=_DIGEST)
    assert sc.evaluate_release(manifest, _policy(), accepted_digests={_BARE}) == []


def test_real_policy_file_loads_and_requires_all_evidence():
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    assert policy["require"] == {
        "sbom": True,
        "provenance": True,
        "vulnerability_scan": True,
        "reproducibility_evidence": True,
    }
    assert sc.policy_from_mapping(policy).fail_on_severity == "high"


# --- strict SBOM evidence (review C) ------------------------------------------


@pytest.mark.parametrize(
    "sbom",
    [
        {"components": "invalid"},        # truthy but not a list
        {"components": []},               # empty
        {"bomFormat": "CycloneDX", "components": "x"},
        {"bomFormat": "CycloneDX", "components": []},
        {"spdxVersion": "SPDX-2.3", "packages": []},
        {"packages": [{"name": "x"}]},    # no recognised format marker
        "not-an-object",
        {},
    ],
)
def test_malformed_or_empty_sbom_is_rejected(sbom):
    with pytest.raises(sc.SupplyChainViolation):
        sc.assert_sbom_present(sbom)


def test_recognised_cyclonedx_and_spdx_sboms_pass():
    sc.assert_sbom_present({"bomFormat": "CycloneDX", "components": [{"name": "fastapi"}]})
    sc.assert_sbom_present({"spdxVersion": "SPDX-2.3", "packages": [{"name": "fastapi"}]})


# --- strict raw-scan merge (review B) -----------------------------------------


def test_merge_trivy_reports_combines_results():
    merged = sc.merge_trivy_reports(
        {"SchemaVersion": 2, "Results": [{"a": 1}]},
        {"SchemaVersion": 2, "Results": [{"b": 2}]},
    )
    assert merged == {"Results": [{"a": 1}, {"b": 2}]}
    sc.assert_scan_evidence(merged)


def test_merge_trivy_reports_accepts_recognised_empty_report():
    # Trivy emits Results: null (or omits it) for a target with no findings; a recognised
    # Trivy report (has SchemaVersion) is a VALID empty scan, not malformed.
    merged = sc.merge_trivy_reports(
        {"SchemaVersion": 2, "Results": [{"a": 1}]},
        {"SchemaVersion": 2, "Results": None},
        {"SchemaVersion": 2},
    )
    assert merged == {"Results": [{"a": 1}]}


@pytest.mark.parametrize(
    "bad",
    [
        {},                                  # no SchemaVersion (e.g. a defaulted missing file)
        {"Results": None},                   # no SchemaVersion
        {"Results": []},                     # no SchemaVersion
        {"Results": "x"},                    # no SchemaVersion
        "not-an-object",
        {"SchemaVersion": 2, "Results": "x"},  # recognised but Results wrong type
    ],
)
def test_merge_trivy_reports_rejects_unrecognised_or_malformed(bad):
    with pytest.raises(sc.SupplyChainViolation):
        sc.merge_trivy_reports({"SchemaVersion": 2, "Results": []}, bad)


# --- pinned tool identity (review A) ------------------------------------------


def test_tool_identity_matches_pinned_policy():
    sc.assert_tool_identity(_TOOLS_POLICY, _TOOLS_EVIDENCE)


def test_tool_identity_rejects_mismatched_checksum():
    bad = {"syft": {"version": "v1.18.1", "archive_sha256": "9" * 64}, "trivy": _TOOLS_EVIDENCE["trivy"]}
    with pytest.raises(sc.SupplyChainViolation):
        sc.assert_tool_identity(_TOOLS_POLICY, bad)


def test_tool_identity_rejects_missing_tool_evidence():
    with pytest.raises(sc.SupplyChainViolation):
        sc.assert_tool_identity(_TOOLS_POLICY, {"syft": _TOOLS_EVIDENCE["syft"]})
    with pytest.raises(sc.SupplyChainViolation):
        sc.assert_tool_identity(_TOOLS_POLICY, {})


def test_release_requires_tool_identity_evidence_when_policy_pins_tools():
    manifest = _valid_manifest()
    del manifest["tools"]
    failures = sc.evaluate_release(manifest, _policy())
    assert any("tool" in f.lower() for f in failures)


def test_release_rejects_drifted_tool_identity():
    manifest = _valid_manifest(tools={"syft": {"version": "v0.0.0", "archive_sha256": "0" * 64}, "trivy": _TOOLS_EVIDENCE["trivy"]})
    failures = sc.evaluate_release(manifest, _policy())
    assert any("tool" in f.lower() for f in failures)


def test_real_policy_pins_checksummed_tools():
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    tools = policy["supply_chain_tools"]
    for name in ("syft", "trivy"):
        assert tools[name]["archive_url"].startswith("https://github.com/")
        assert "/main/" not in tools[name]["archive_url"]
        assert len(tools[name]["archive_sha256"]) == 64


# --- base-image risk baseline / inherited-finding attribution -----------------

_INHERITED = {"id": "CVE-9", "package": "perl-base", "installed_version": "5.36", "severity": "HIGH", "status": "affected"}


def _entry(**o):
    e = dict(_INHERITED)
    e.update(o)
    return e


def test_inherited_unfixable_finding_in_baseline_is_accepted():
    v = _vuln("CVE-9", "perl-base", "5.36", "HIGH", "affected")
    dec = sc.evaluate_image_vulnerabilities(
        _trivy_report([v]), _trivy_report([v]), _base_baseline([_entry()]), base_digest=_BASE_DIGEST
    )
    assert dec.passed and len(dec.accepted_inherited) == 1


def test_app_introduced_high_blocks():
    img = _trivy_report([_vuln("CVE-APP", "fastapi", "1", "HIGH")])
    dec = sc.evaluate_image_vulnerabilities(img, _trivy_report([]), _base_baseline(), base_digest=_BASE_DIGEST)
    assert not dec.passed and dec.blocking[0]["block_reason"] == "app_introduced"


def test_fixable_inherited_finding_blocks():
    v = _vuln("CVE-9", "perl-base", "5.36", "HIGH", "affected", fixed="5.36.1")
    dec = sc.evaluate_image_vulnerabilities(
        _trivy_report([v]), _trivy_report([v]), _base_baseline(), base_digest=_BASE_DIGEST
    )
    assert not dec.passed and dec.blocking[0]["block_reason"] == "fix_available"


def test_inherited_but_base_digest_mismatch_blocks():
    v = _vuln("CVE-9", "perl-base", "5.36", "HIGH", "affected")
    dec = sc.evaluate_image_vulnerabilities(
        _trivy_report([v]), _trivy_report([v]), _base_baseline([_entry()]),
        base_digest="sha256:" + "f" * 64,
    )
    assert not dec.passed and dec.blocking[0]["block_reason"] == "base_digest_mismatch"


def test_inherited_but_not_in_baseline_blocks():
    v = _vuln("CVE-9", "perl-base", "5.36", "HIGH", "affected")
    dec = sc.evaluate_image_vulnerabilities(
        _trivy_report([v]), _trivy_report([v]), _base_baseline(), base_digest=_BASE_DIGEST
    )
    assert not dec.passed and dec.blocking[0]["block_reason"] == "not_in_reviewed_baseline"


def test_inherited_but_baseline_expired_blocks():
    v = _vuln("CVE-9", "perl-base", "5.36", "HIGH", "affected")
    bl = _base_baseline([_entry()], valid_until="2000-01-01")
    dec = sc.evaluate_image_vulnerabilities(
        _trivy_report([v]), _trivy_report([v]), bl, base_digest=_BASE_DIGEST, on=date(2026, 6, 24)
    )
    assert not dec.passed and dec.blocking[0]["block_reason"] == "baseline_expired"


def test_unknown_severity_image_finding_blocks():
    img = _trivy_report([_vuln("CVE-U", "p", "1", "weird")])
    dec = sc.evaluate_image_vulnerabilities(img, _trivy_report([]), _base_baseline(), base_digest=_BASE_DIGEST)
    assert not dec.passed and dec.blocking[0]["block_reason"] == "unknown_severity"


def test_non_nofix_status_inherited_blocks():
    v = _vuln("CVE-9", "perl-base", "5.36", "HIGH", "fixed")
    dec = sc.evaluate_image_vulnerabilities(
        _trivy_report([v]), _trivy_report([v]), _base_baseline(), base_digest=_BASE_DIGEST
    )
    assert not dec.passed and dec.blocking[0]["block_reason"] == "unknown_or_unacceptable_status"


def test_below_threshold_image_findings_ignored():
    dec = sc.evaluate_image_vulnerabilities(
        _trivy_report([_vuln("CVE-L", "p", "1", "MEDIUM")]), _trivy_report([]), _base_baseline(), base_digest=_BASE_DIGEST
    )
    assert dec.passed


@pytest.mark.parametrize(
    "mapping",
    [
        {"base_image": {"digest": "not-a-digest"}},
        {"base_image": {"digest": _BASE_DIGEST}, "accepted_inherited_findings": [{"id": "C", "package": "p", "installed_version": "1", "severity": "HIGH", "status": "affected"}]},  # no expires + no valid_until
        {"base_image": {"digest": _BASE_DIGEST, "valid_until": "2099-01-01"}, "accepted_inherited_findings": [{"id": "C", "package": "p", "installed_version": "1", "severity": "HIGH", "status": "fixed"}]},  # bad status
        {"base_image": {"digest": _BASE_DIGEST, "valid_until": "2099-01-01"}, "accepted_inherited_findings": [{"id": "C", "package": "p", "installed_version": "1", "severity": "HIGH", "status": "affected", "fixed_version": "1.1"}]},  # has fix
    ],
)
def test_load_base_baseline_rejects_malformed(mapping):
    with pytest.raises(sc.SupplyChainViolation):
        sc.load_base_baseline(mapping)


def test_committed_base_baseline_matches_policy_pinned_base():
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    baseline = yaml.safe_load((SERVICE_ROOT / "accepted-base-findings.yaml").read_text(encoding="utf-8"))
    pinned = policy["pinned_base_images"][0]
    assert baseline["base_image"]["digest"] == "sha256:" + pinned.split("@sha256:")[-1]
    loaded = sc.load_base_baseline(baseline)
    assert loaded["base_digest"] == baseline["base_image"]["digest"]
    assert len(loaded["entries"]) == len(baseline["accepted_inherited_findings"]) >= 1


def test_release_passes_with_baselined_inherited_high():
    v = _vuln("CVE-9", "perl-base", "5.36", "HIGH", "affected")
    manifest = _valid_manifest(
        image_scan=_trivy_report([v]), base_scan=_trivy_report([v]),
        base_image={"ref": "x@" + _BASE_DIGEST, "digest": _BASE_DIGEST},
    )
    assert sc.evaluate_release(manifest, _policy(), base_baseline=_base_baseline([_entry()])) == []


def test_release_fails_when_baseline_base_digest_mismatches_image_base():
    v = _vuln("CVE-9", "perl-base", "5.36", "HIGH", "affected")
    manifest = _valid_manifest(
        image_scan=_trivy_report([v]), base_scan=_trivy_report([v]),
        base_image={"ref": "x@" + _BASE_DIGEST, "digest": _BASE_DIGEST},
    )
    other = _base_baseline([_entry()], digest="sha256:" + "f" * 64)
    failures = sc.evaluate_release(manifest, _policy(), base_baseline=other)
    assert any("vulnerability" in f.lower() for f in failures)


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
