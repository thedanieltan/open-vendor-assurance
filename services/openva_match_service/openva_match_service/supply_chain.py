"""Deployment-artifact supply-chain policy gate (WP-02E).

Pure, deterministic policy logic for the hosted match-service container artifact, plus
a thin CLI the release-image workflow invokes. This module DOES NOT build images, push
to a registry, provision anything, or deploy: it only *evaluates* artifact evidence and
fails closed when the supply-chain controls are not satisfied. The architecture and
posture are governed by ADR-0001 and ADR-0006; nothing here makes the hosted endpoint
live (the decision-only posture in docs/operations/contracts/hosted-deployment.yaml is
untouched).

Fail-closed throughout: missing, malformed, or unrecognised evidence raises
SupplyChainViolation rather than normalising to a pass. The core functions operate on
plain dicts/lists so they are dependency-free and unit testable; YAML/JSON parsing
happens only at the CLI boundary.
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
# A bare manifest digest (sha256:<64 hex>), as emitted by BuildKit containerimage.digest.
_BARE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
# A Dockerfile FROM line, capturing the image reference (ignoring "AS <stage>").
_FROM_RE = re.compile(r"^\s*FROM\s+(?P<ref>\S+)(?:\s+AS\s+\S+)?\s*$", re.IGNORECASE)
# Severities ranked; anything not in this map is unknown and blocks (fail closed).
_SEVERITY_RANK = {"negligible": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


class SupplyChainViolation(ValueError):
    """A supply-chain control was not satisfied. The release must fail closed."""


# --- immutable artifact reference ---------------------------------------------


def is_digest_pinned(image_ref: str) -> bool:
    """True iff the reference pins the image by an ``@sha256:<64 hex>`` digest."""
    return bool(image_ref) and bool(_DIGEST_RE.search(image_ref.strip()))


def manifest_digest_of(image_ref: str) -> str:
    """The bare ``sha256:<hex>`` manifest digest from a digest-pinned reference."""
    return "sha256:" + image_ref.strip().split("@sha256:")[-1]


def assert_immutable_image_ref(image_ref: str, *, field_name: str = "image reference") -> str:
    """Return the reference if it is digest-pinned; otherwise fail closed."""
    ref = (image_ref or "").strip()
    if not is_digest_pinned(ref):
        raise SupplyChainViolation(
            f"{field_name} must be an immutable digest (name@sha256:<64 hex>), "
            f"got mutable/!pinned reference: {ref!r}"
        )
    return ref


# --- pinned base-image policy -------------------------------------------------


def dockerfile_base_refs(dockerfile_text: str) -> list[str]:
    refs: list[str] = []
    for line in dockerfile_text.splitlines():
        match = _FROM_RE.match(line)
        if match:
            refs.append(match.group("ref").strip())
    return refs


def unpinned_base_refs(dockerfile_text: str) -> list[str]:
    return [
        ref
        for ref in dockerfile_base_refs(dockerfile_text)
        if ref.lower() != "scratch" and not is_digest_pinned(ref)
    ]


def assert_dockerfile_base_pinned(
    dockerfile_text: str, *, allowed_bases: Iterable[str] | None = None
) -> list[str]:
    """Return the pinned base refs; fail closed if any ``FROM`` is not digest-pinned, or
    (when ``allowed_bases`` is given) if any ``FROM`` is not in the approved pin list."""
    refs = dockerfile_base_refs(dockerfile_text)
    if not refs:
        raise SupplyChainViolation("Dockerfile declares no FROM base image")
    unpinned = unpinned_base_refs(dockerfile_text)
    if unpinned:
        raise SupplyChainViolation(
            "every Dockerfile FROM must be digest-pinned; unpinned base(s): " + ", ".join(unpinned)
        )
    if allowed_bases is not None:
        allowed = set(allowed_bases)
        unapproved = [r for r in refs if r.lower() != "scratch" and r not in allowed]
        if unapproved:
            raise SupplyChainViolation(
                "Dockerfile FROM not in the approved pinned_base_images policy: "
                + ", ".join(unapproved)
            )
    return refs


# --- SBOM + provenance presence -----------------------------------------------


def assert_sbom_present(sbom: dict[str, Any]) -> None:
    """Fail closed unless ``sbom`` is a RECOGNISED, non-empty SBOM. A truthy-but-malformed
    value (e.g. ``{"components": "invalid"}``) must NOT pass as a non-empty SBOM."""
    if not isinstance(sbom, dict):
        raise SupplyChainViolation("SBOM is missing or not an object")
    if sbom.get("bomFormat") == "CycloneDX":
        components = sbom.get("components")
        if not isinstance(components, list) or not components:
            raise SupplyChainViolation("CycloneDX SBOM components must be a non-empty list")
        return
    if isinstance(sbom.get("spdxVersion"), str):
        packages = sbom.get("packages")
        if not isinstance(packages, list) or not packages:
            raise SupplyChainViolation("SPDX SBOM packages must be a non-empty list")
        return
    raise SupplyChainViolation("unrecognised or empty SBOM evidence (expected CycloneDX or SPDX)")


def assert_provenance_present(provenance: dict[str, Any], *, artifact_digest: str | None = None) -> None:
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
class VulnException:
    vuln_id: str
    reason: str
    expires: date  # required; an exception with no expiry is rejected at load time

    def active_on(self, on: date) -> bool:
        return on <= self.expires


@dataclass(frozen=True)
class VulnPolicy:
    fail_on_severity: str = "high"
    exceptions: dict[str, VulnException] = field(default_factory=dict)

    @property
    def threshold_rank(self) -> int:
        return _SEVERITY_RANK[self.fail_on_severity.lower()]


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


def assert_scan_evidence(scan: dict[str, Any]) -> None:
    """Fail closed unless ``scan`` is a recognised scanner envelope with correctly typed
    lists. An empty/unknown object (e.g. a missing report defaulted to ``{}``) or a
    malformed envelope (``Results: null``) must raise, not normalise to zero findings."""
    if not isinstance(scan, dict):
        raise SupplyChainViolation("scan report is missing or not an object")
    recognised = False
    for key in ("Results", "matches", "findings"):
        if key in scan:
            if not isinstance(scan[key], list):
                raise SupplyChainViolation(f"scan report field {key!r} must be a list (malformed report)")
            recognised = True
    if not recognised:
        raise SupplyChainViolation(
            "unrecognised scan envelope (expected Trivy 'Results', Grype 'matches', or 'findings')"
        )


def merge_trivy_reports(*reports: dict[str, Any]) -> dict[str, Any]:
    """Strictly combine raw Trivy reports into one ``{"Results": [...]}`` envelope.

    Fail-closed: a report that is not an object, or lacks a list-valued ``Results``, raises
    rather than being coerced to ``[]``. This prevents the workflow from re-wrapping a
    malformed/empty raw report into a clean recognised envelope that bypasses
    ``assert_scan_evidence``."""
    combined: list[dict[str, Any]] = []
    for index, report in enumerate(reports):
        if not isinstance(report, dict):
            raise SupplyChainViolation(f"Trivy report {index} is not an object")
        if "Results" not in report or not isinstance(report["Results"], list):
            raise SupplyChainViolation(f"Trivy report {index} must contain a list-valued 'Results' field")
        combined.extend(report["Results"])
    return {"Results": combined}


def evaluate_scan(
    findings: Iterable[dict[str, Any]],
    policy: VulnPolicy,
    *,
    on: date | None = None,
) -> ScanDecision:
    """Partition scan findings into blocking vs documented-exception, fail-closed.

    Unknown severity ALWAYS blocks and can never be exempted. Only KNOWN severities at or
    above the threshold are eligible for an unexpired documented exception."""
    today = on or datetime.now(timezone.utc).date()
    blocking: list[dict[str, Any]] = []
    exempted: list[dict[str, Any]] = []
    expired: list[str] = []
    for finding in findings:
        rank = _finding_rank(finding)
        if rank is None:
            # Unknown severity: always blocks; exceptions do not apply.
            blocking.append(finding)
            continue
        if rank < policy.threshold_rank:
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
            f"'{policy.fail_on_severity}' (or of unknown severity) fail the release closed: {ids}"
        )
    return decision


# --- reproducibility / equivalence evidence -----------------------------------


def assert_reproducibility_evidence(report: dict[str, Any], *, artifact_digest: str | None = None) -> None:
    """Fail closed unless the rebuild produced the SAME OCI manifest digest as the build.

    Package-set equivalence is supplementary, not a substitute: the primary proof is
    digest-to-digest equality of two independent builds from the same pinned inputs."""
    if not isinstance(report, dict):
        raise SupplyChainViolation("reproducibility evidence is missing or not an object")
    required = (
        "manifest_digest",
        "rebuild_manifest_digest",
        "digests_match",
        "equivalent",
        "package_count",
        "rebuild_package_count",
    )
    missing = [k for k in required if k not in report]
    if missing:
        raise SupplyChainViolation(f"reproducibility evidence missing field(s): {', '.join(missing)}")
    for key in ("manifest_digest", "rebuild_manifest_digest"):
        if not _BARE_DIGEST_RE.fullmatch(str(report[key])):
            raise SupplyChainViolation(f"reproducibility {key} is not a sha256 manifest digest")
    if report["manifest_digest"] != report["rebuild_manifest_digest"] or report["digests_match"] is not True:
        raise SupplyChainViolation(
            "build is not reproducible: rebuilt OCI manifest digest differs from the original "
            f"({report['manifest_digest']} != {report['rebuild_manifest_digest']})"
        )
    if report["equivalent"] is not True:
        raise SupplyChainViolation("reproducibility package set is not equivalent across rebuilds")
    pc, rpc = report["package_count"], report["rebuild_package_count"]
    if not isinstance(pc, int) or pc <= 0:
        raise SupplyChainViolation("reproducibility package_count must be a positive integer")
    if pc != rpc:
        raise SupplyChainViolation(f"reproducibility package counts differ ({pc} != {rpc})")
    if artifact_digest is not None and report["manifest_digest"] != artifact_digest:
        raise SupplyChainViolation(
            "reproducibility evidence does not describe the deployed artifact digest "
            f"({report['manifest_digest']} != {artifact_digest})"
        )


# --- rollback by prior ACCEPTED digest ----------------------------------------


def load_accepted_digests(mapping: dict[str, Any]) -> set[str]:
    """The set of accepted prior-release manifest digests from the accepted-release
    ledger (``accepted_releases: [{manifest_digest: sha256:...}]``)."""
    out: set[str] = set()
    for entry in (mapping or {}).get("accepted_releases") or []:
        digest = str((entry or {}).get("manifest_digest", "")).strip()
        if not _BARE_DIGEST_RE.fullmatch(digest):
            raise SupplyChainViolation(f"accepted-release ledger has a malformed manifest_digest: {digest!r}")
        out.add(digest)
    return out


def assert_rollback_target(image_ref: str, accepted_digests: set[str] | None) -> str:
    """A rollback target must be a digest reference AND a prior ACCEPTED release digest.

    Digest syntax alone is insufficient: the manifest digest must appear in the accepted
    -release ledger, so an arbitrary (even well-formed) digest cannot be rolled back to."""
    ref = assert_immutable_image_ref(image_ref, field_name="rollback target")
    digest = manifest_digest_of(ref)
    if not accepted_digests or digest not in accepted_digests:
        raise SupplyChainViolation(
            f"rollback target {digest} is not a prior accepted release (not in the accepted-release ledger)"
        )
    return ref


# --- supply-chain tool identity (pinned, checksum-verified) --------------------


def assert_tool_identity(policy_tools: dict[str, Any], evidence_tools: dict[str, Any]) -> None:
    """Fail closed unless the recorded tool evidence matches the policy's pinned tools.

    For every tool the policy pins (``supply_chain_tools``), the evidence must record the
    same ``version`` and ``archive_sha256``; a missing or mismatched tool identity raises.
    This binds the actually-installed scanner/SBOM tooling to the reviewed, checksummed
    pins so the gate cannot drift to unpinned tooling."""
    if not isinstance(policy_tools, dict) or not policy_tools:
        raise SupplyChainViolation("policy declares no pinned supply_chain_tools")
    if not isinstance(evidence_tools, dict):
        raise SupplyChainViolation("release evidence carries no tool identity record")
    for name, pinned in policy_tools.items():
        got = evidence_tools.get(name)
        if not isinstance(got, dict):
            raise SupplyChainViolation(f"release evidence is missing tool identity for {name!r}")
        for key in ("version", "archive_sha256"):
            if str(got.get(key, "")) != str((pinned or {}).get(key, "")):
                raise SupplyChainViolation(
                    f"tool {name!r} {key} evidence {got.get(key)!r} does not match the pinned policy "
                    f"value {(pinned or {}).get(key)!r}"
                )
        if not _BARE_DIGEST_RE.fullmatch("sha256:" + str((pinned or {}).get("archive_sha256", ""))):
            raise SupplyChainViolation(f"tool {name!r} archive_sha256 is not a 64-hex sha256 in the policy")


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
        if vuln_id in exceptions:
            raise SupplyChainViolation(f"duplicate vulnerability exception id: {vuln_id}")
        expires_raw = raw.get("expires")
        if not expires_raw:
            raise SupplyChainViolation(f"vulnerability exception {vuln_id} requires an 'expires' date")
        try:
            expires = date.fromisoformat(str(expires_raw))
        except ValueError as exc:
            raise SupplyChainViolation(
                f"vulnerability exception {vuln_id} has an invalid 'expires' date: {expires_raw!r}"
            ) from exc
        exceptions[vuln_id] = VulnException(vuln_id=vuln_id, reason=reason, expires=expires)
    return VulnPolicy(fail_on_severity=fail_on, exceptions=exceptions)


def _scan_findings(scan: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise a recognised scanner report into ``{id, severity}`` findings.

    Call ``assert_scan_evidence`` first; this assumes a recognised, well-typed envelope."""
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


def evaluate_release(
    manifest: dict[str, Any],
    policy_mapping: dict[str, Any],
    *,
    accepted_digests: set[str] | None = None,
    on: date | None = None,
) -> list[str]:
    """Run every release gate against a manifest; return failure messages (empty == pass).

    The policy's ``require`` flags and ``pinned_base_images`` are CONSUMED here (not
    documentary): a required-but-missing piece of evidence fails closed.

    manifest keys: image_ref (digest, required), dockerfile, sbom, provenance, scan,
    reproducibility, rollback_ref."""
    failures: list[str] = []
    require = (policy_mapping or {}).get("require") or {}
    pinned_bases = (policy_mapping or {}).get("pinned_base_images")
    pinned_tools = (policy_mapping or {}).get("supply_chain_tools")

    artifact_digest: str | None = None
    try:
        artifact_ref = assert_immutable_image_ref(manifest.get("image_ref", ""), field_name="deployed artifact")
        artifact_digest = manifest_digest_of(artifact_ref)
    except SupplyChainViolation as exc:
        failures.append(str(exc))

    # Pinned base image (enforced against the policy's approved list when present).
    if "dockerfile" in manifest:
        try:
            assert_dockerfile_base_pinned(manifest["dockerfile"], allowed_bases=pinned_bases)
        except SupplyChainViolation as exc:
            failures.append(str(exc))
    elif pinned_bases is not None:
        failures.append("release manifest is missing the 'dockerfile' needed to verify the pinned base policy")

    # Required evidence (policy.require consumed). Map require flags -> manifest keys.
    required_map = {
        "sbom": require.get("sbom"),
        "provenance": require.get("provenance"),
        "scan": require.get("vulnerability_scan"),
        "reproducibility": require.get("reproducibility_evidence"),
    }
    for manifest_key, is_required in required_map.items():
        if is_required and manifest_key not in manifest:
            failures.append(f"release manifest is missing required '{manifest_key}' evidence")

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
            assert_scan_evidence(manifest["scan"])
            assert_scan_passes(_scan_findings(manifest["scan"]), policy_from_mapping(policy_mapping), on=on)
        except SupplyChainViolation as exc:
            failures.append(str(exc))
    if "reproducibility" in manifest:
        try:
            assert_reproducibility_evidence(manifest["reproducibility"], artifact_digest=artifact_digest)
        except SupplyChainViolation as exc:
            failures.append(str(exc))
    if pinned_tools:
        try:
            assert_tool_identity(pinned_tools, manifest.get("tools") or {})
        except SupplyChainViolation as exc:
            failures.append(str(exc))
    if manifest.get("rollback_ref"):
        try:
            assert_rollback_target(manifest["rollback_ref"], accepted_digests)
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
    p_df.add_argument("--policy", help="optional policy YAML/JSON to enforce the pinned_base_images list")

    p_rel = sub.add_parser("check-release", help="run every release gate against a manifest")
    p_rel.add_argument("--manifest", required=True, help="release manifest JSON")
    p_rel.add_argument("--policy", required=True, help="supply-chain policy YAML/JSON")
    p_rel.add_argument("--accepted-releases", help="accepted-release ledger YAML/JSON (for rollback validation)")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "check-image-ref":
            ref = assert_immutable_image_ref(args.ref, field_name="deployed artifact")
            print(f"OK: immutable digest reference {ref}")
            return 0
        if args.cmd == "check-dockerfile":
            allowed = _load(args.policy).get("pinned_base_images") if args.policy else None
            refs = assert_dockerfile_base_pinned(
                open(args.path, encoding="utf-8").read(), allowed_bases=allowed
            )
            print(f"OK: {len(refs)} digest-pinned base image(s): {', '.join(refs)}")
            return 0
        if args.cmd == "check-release":
            accepted = load_accepted_digests(_load(args.accepted_releases)) if args.accepted_releases else None
            failures = evaluate_release(_load(args.manifest), _load(args.policy), accepted_digests=accepted)
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
