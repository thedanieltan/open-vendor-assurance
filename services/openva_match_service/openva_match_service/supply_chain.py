"""Deployment-artifact supply-chain policy gate (WP-02E).

Pure, deterministic policy logic for the hosted match-service container artifact, plus
a thin CLI the release-image workflow invokes. This module DOES NOT build images, push
to a registry, provision anything, or deploy: it only *evaluates* artifact evidence and
fails closed when the supply-chain controls are not satisfied. The architecture and
posture are governed by ADR-0001 and ADR-0006; nothing here makes the hosted endpoint
live (the decision-only posture in docs/operations/contracts/hosted-deployment.yaml is
untouched).

The release flow it gates enforces, fail-closed:
  - the deployable artifact reference is an IMMUTABLE digest (``...@sha256:<64hex>``),
    never a mutable tag (``:latest``, ``:v1``, an untagged name);
  - every Dockerfile ``FROM`` is digest-pinned (pinned base-image policy);
  - an SBOM is present and non-empty;
  - build provenance / attestation is present and binds the artifact digest;
  - dependency + container-image vulnerability scan findings at/above the policy
    threshold fail the release UNLESS covered by a documented, unexpired exception;
    a finding of unknown severity is treated as blocking (fail closed).

The core functions operate on plain dicts/lists so they are dependency-free and unit
testable; YAML/JSON parsing happens only at the CLI boundary.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable

# An immutable OCI reference pins the manifest by digest: name[:tag]@sha256:<64 hex>.
_DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}$")
# A Dockerfile FROM line, capturing the image reference (ignoring "AS <stage>").
_FROM_RE = re.compile(r"^\s*FROM\s+(?P<ref>\S+)(?:\s+AS\s+\S+)?\s*$", re.IGNORECASE)
# Severities ranked; anything not in this map is unknown and blocks (fail closed).
_SEVERITY_RANK = {"negligible": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


class SupplyChainViolation(ValueError):
    """A supply-chain control was not satisfied. The release must fail closed."""


# --- immutable artifact reference ---------------------------------------------


def is_digest_pinned(image_ref: str) -> bool:
    """True iff the reference pins the image by an ``@sha256:<64 hex>`` digest.

    A bare name, a tag (``:latest``/``:v1``), or a malformed digest is NOT pinned."""
    return bool(image_ref) and bool(_DIGEST_RE.search(image_ref.strip()))


def assert_immutable_image_ref(image_ref: str, *, field_name: str = "image reference") -> str:
    """Return the reference if it is digest-pinned; otherwise fail closed.

    This is the check that prevents the release flow from ever silently deploying a
    mutable tag — the deployed artifact reference MUST be a digest."""
    ref = (image_ref or "").strip()
    if not is_digest_pinned(ref):
        raise SupplyChainViolation(
            f"{field_name} must be an immutable digest (name@sha256:<64 hex>), "
            f"got mutable/!pinned reference: {ref!r}"
        )
    return ref


# --- pinned base-image policy -------------------------------------------------


def dockerfile_base_refs(dockerfile_text: str) -> list[str]:
    """Every ``FROM`` image reference in a Dockerfile, in order."""
    refs: list[str] = []
    for line in dockerfile_text.splitlines():
        match = _FROM_RE.match(line)
        if match:
            refs.append(match.group("ref").strip())
    return refs


def unpinned_base_refs(dockerfile_text: str) -> list[str]:
    """``FROM`` references that are NOT digest-pinned (a ``scratch`` base is exempt)."""
    return [
        ref
        for ref in dockerfile_base_refs(dockerfile_text)
        if ref.lower() != "scratch" and not is_digest_pinned(ref)
    ]


def assert_dockerfile_base_pinned(dockerfile_text: str) -> list[str]:
    """Return the pinned base refs; fail closed if any ``FROM`` is not digest-pinned."""
    if not dockerfile_base_refs(dockerfile_text):
        raise SupplyChainViolation("Dockerfile declares no FROM base image")
    unpinned = unpinned_base_refs(dockerfile_text)
    if unpinned:
        raise SupplyChainViolation(
            "every Dockerfile FROM must be digest-pinned; unpinned base(s): " + ", ".join(unpinned)
        )
    return dockerfile_base_refs(dockerfile_text)


# --- SBOM + provenance presence -----------------------------------------------


def assert_sbom_present(sbom: dict[str, Any]) -> None:
    """Fail closed unless the SBOM declares at least one component/package.

    Accepts CycloneDX (``components``) or SPDX (``packages``) shapes; an empty or
    missing component list is a missing-SBOM failure."""
    if not isinstance(sbom, dict):
        raise SupplyChainViolation("SBOM is missing or not an object")
    components = sbom.get("components")
    packages = sbom.get("packages")
    count = len(components or []) + len(packages or [])
    if count <= 0:
        raise SupplyChainViolation("SBOM contains no components/packages (missing or empty SBOM)")


def assert_provenance_present(provenance: dict[str, Any], *, artifact_digest: str | None = None) -> None:
    """Fail closed unless an attestation is present and (if given) binds the digest.

    Accepts an in-toto / SLSA-style statement: a ``predicateType`` and a ``subject``
    whose entries carry a ``sha256`` digest. When ``artifact_digest`` is provided, at
    least one subject digest must match it (the provenance must describe THIS image)."""
    if not isinstance(provenance, dict):
        raise SupplyChainViolation("build provenance/attestation is missing or not an object")
    if not provenance.get("predicateType"):
        raise SupplyChainViolation("provenance is missing predicateType (not an attestation)")
    subjects = provenance.get("subject") or []
    digests = {
        str(((s or {}).get("digest") or {}).get("sha256", "")).lower()
        for s in subjects
        if isinstance(s, dict)
    }
    digests.discard("")
    if not digests:
        raise SupplyChainViolation("provenance subject carries no sha256 digest")
    if artifact_digest is not None:
        want = artifact_digest.split("sha256:")[-1].lower()
        if want not in digests:
            raise SupplyChainViolation(
                "provenance does not bind the deployed artifact digest "
                f"(subject digests {sorted(digests)} do not include {want})"
            )


# --- vulnerability scan, fail-closed ------------------------------------------


@dataclass(frozen=True)
class VulnPolicy:
    """Fail-closed vulnerability policy. Findings whose severity rank is >= the
    threshold block the release unless a documented, unexpired exception covers the
    vulnerability id. Unknown severities always block."""

    fail_on_severity: str = "high"  # high and above (high, critical) block by default
    exceptions: dict[str, "VulnException"] = field(default_factory=dict)

    @property
    def threshold_rank(self) -> int:
        return _SEVERITY_RANK[self.fail_on_severity.lower()]


@dataclass(frozen=True)
class VulnException:
    vuln_id: str
    reason: str
    expires: date | None  # None == never expires (discouraged; flagged in summary)

    def active_on(self, on: date) -> bool:
        return self.expires is None or on <= self.expires


@dataclass(frozen=True)
class ScanDecision:
    blocking: list[dict[str, Any]]
    exempted: list[dict[str, Any]]
    expired_exceptions: list[str]

    @property
    def passed(self) -> bool:
        return not self.blocking


def _finding_rank(finding: dict[str, Any]) -> int | None:
    sev = str(finding.get("severity", "")).strip().lower()
    return _SEVERITY_RANK.get(sev)  # None == unknown severity (blocks, fail closed)


def evaluate_scan(
    findings: Iterable[dict[str, Any]],
    policy: VulnPolicy,
    *,
    on: date | None = None,
) -> ScanDecision:
    """Partition scan findings into blocking vs documented-exception, fail-closed.

    A finding blocks when its severity rank >= the policy threshold (or is unknown),
    UNLESS an unexpired exception covers its id. Expired exceptions do NOT suppress a
    finding (they are reported so the allowlist cannot rot silently)."""
    today = on or datetime.now(timezone.utc).date()
    blocking: list[dict[str, Any]] = []
    exempted: list[dict[str, Any]] = []
    expired: list[str] = []
    for finding in findings:
        rank = _finding_rank(finding)
        is_at_threshold = rank is None or rank >= policy.threshold_rank
        if not is_at_threshold:
            continue
        vuln_id = str(finding.get("id", "")).strip()
        exc = policy.exceptions.get(vuln_id)
        if exc and exc.active_on(today):
            exempted.append(finding)
        else:
            if exc and not exc.active_on(today) and vuln_id not in expired:
                expired.append(vuln_id)
            blocking.append(finding)
    return ScanDecision(blocking=blocking, exempted=exempted, expired_exceptions=expired)


def assert_scan_passes(
    findings: Iterable[dict[str, Any]], policy: VulnPolicy, *, on: date | None = None
) -> ScanDecision:
    decision = evaluate_scan(findings, policy, on=on)
    if not decision.passed:
        ids = ", ".join(sorted({str(f.get("id", "?")) for f in decision.blocking}))
        raise SupplyChainViolation(
            f"{len(decision.blocking)} unapproved vulnerability finding(s) at/above "
            f"'{policy.fail_on_severity}' fail the release closed: {ids}"
        )
    return decision


# --- rollback by prior accepted digest ----------------------------------------


def assert_rollback_target(image_ref: str) -> str:
    """A rollback target must itself be a prior accepted immutable digest."""
    return assert_immutable_image_ref(image_ref, field_name="rollback target")


# --- policy loading + composite release gate ----------------------------------


def policy_from_mapping(mapping: dict[str, Any]) -> VulnPolicy:
    vuln = (mapping or {}).get("vulnerability_policy") or {}
    fail_on = str(vuln.get("fail_on_severity", "high")).lower()
    if fail_on not in _SEVERITY_RANK:
        raise SupplyChainViolation(f"vulnerability_policy.fail_on_severity invalid: {fail_on!r}")
    exceptions: dict[str, VulnException] = {}
    for raw in vuln.get("exceptions") or []:
        vuln_id = str(raw.get("id", "")).strip()
        reason = str(raw.get("reason", "")).strip()
        if not vuln_id or not reason:
            raise SupplyChainViolation("each vulnerability exception requires 'id' and 'reason'")
        expires_raw = raw.get("expires")
        expires = date.fromisoformat(str(expires_raw)) if expires_raw else None
        exceptions[vuln_id] = VulnException(vuln_id=vuln_id, reason=reason, expires=expires)
    return VulnPolicy(fail_on_severity=fail_on, exceptions=exceptions)


def _scan_findings(scan: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise a scanner report into a list of ``{id, severity}`` findings.

    Accepts a Trivy-style ``Results[].Vulnerabilities[]`` or a Grype-style
    ``matches[].vulnerability`` document, or a plain ``findings`` list."""
    if "findings" in scan:
        return list(scan["findings"] or [])
    out: list[dict[str, Any]] = []
    for result in scan.get("Results") or []:
        for vuln in (result or {}).get("Vulnerabilities") or []:
            out.append({"id": vuln.get("VulnerabilityID"), "severity": vuln.get("Severity")})
    for match in scan.get("matches") or []:
        vuln = (match or {}).get("vulnerability") or {}
        out.append({"id": vuln.get("id"), "severity": vuln.get("severity")})
    return out


def evaluate_release(manifest: dict[str, Any], policy_mapping: dict[str, Any], *, on: date | None = None) -> list[str]:
    """Run every release gate against a manifest; return a list of failure messages
    (empty == the release passes). The manifest carries the artifact evidence:

        image_ref:   the deployable digest reference (required)
        dockerfile:  Dockerfile text (optional; base-pin checked when present)
        sbom:        SBOM document (required)
        provenance:  attestation document (required)
        scan:        scanner report (required)
        rollback_ref: prior accepted digest (optional; checked when present)
    """
    failures: list[str] = []
    artifact_digest = None
    try:
        artifact_digest = assert_immutable_image_ref(manifest.get("image_ref", ""), field_name="deployed artifact")
    except SupplyChainViolation as exc:
        failures.append(str(exc))
    if "dockerfile" in manifest:
        try:
            assert_dockerfile_base_pinned(manifest["dockerfile"])
        except SupplyChainViolation as exc:
            failures.append(str(exc))
    for required in ("sbom", "provenance", "scan"):
        if required not in manifest:
            failures.append(f"release manifest is missing required '{required}' evidence")
    if "sbom" in manifest:
        try:
            assert_sbom_present(manifest["sbom"])
        except SupplyChainViolation as exc:
            failures.append(str(exc))
    if "provenance" in manifest:
        try:
            assert_provenance_present(manifest["provenance"], artifact_digest=artifact_digest)
        except SupplyChainViolation as exc:
            failures.append(str(exc))
    if "scan" in manifest:
        try:
            assert_scan_passes(_scan_findings(manifest["scan"]), policy_from_mapping(policy_mapping), on=on)
        except SupplyChainViolation as exc:
            failures.append(str(exc))
    if manifest.get("rollback_ref"):
        try:
            assert_rollback_target(manifest["rollback_ref"])
        except SupplyChainViolation as exc:
            failures.append(str(exc))
    return failures


# --- CLI ----------------------------------------------------------------------


def _load(path: str) -> dict[str, Any]:
    text = open(path, encoding="utf-8").read()
    if path.endswith((".yaml", ".yml")):
        import yaml  # lazy: only the CLI needs YAML; core logic stays dependency-free

        return yaml.safe_load(text) or {}
    return json.loads(text or "{}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="openva-supply-chain",
        description="Fail-closed supply-chain policy gate for the hosted match-service artifact (WP-02E). "
        "Evaluates artifact evidence only; never builds, pushes, provisions, or deploys.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ref = sub.add_parser("check-image-ref", help="fail unless the reference is an immutable digest")
    p_ref.add_argument("--ref", required=True)

    p_df = sub.add_parser("check-dockerfile", help="fail unless every FROM is digest-pinned")
    p_df.add_argument("--path", required=True)

    p_rel = sub.add_parser("check-release", help="run every release gate against a manifest")
    p_rel.add_argument("--manifest", required=True, help="release manifest JSON")
    p_rel.add_argument("--policy", required=True, help="supply-chain policy YAML/JSON")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "check-image-ref":
            ref = assert_immutable_image_ref(args.ref, field_name="deployed artifact")
            print(f"OK: immutable digest reference {ref}")
            return 0
        if args.cmd == "check-dockerfile":
            refs = assert_dockerfile_base_pinned(open(args.path, encoding="utf-8").read())
            print(f"OK: {len(refs)} digest-pinned base image(s): {', '.join(refs)}")
            return 0
        if args.cmd == "check-release":
            failures = evaluate_release(_load(args.manifest), _load(args.policy))
            if failures:
                print(f"FAIL: {len(failures)} supply-chain gate violation(s):", file=sys.stderr)
                for msg in failures:
                    print(f"  - {msg}", file=sys.stderr)
                return 1
            print("OK: all supply-chain release gates passed")
            return 0
    except SupplyChainViolation as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"FAIL: required evidence file not found: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
