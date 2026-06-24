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


# How the gate treats UNKNOWN-severity findings, declared by the policy:
#   block                                   -> UNKNOWN always blocks; never accepted, even
#                                              for an exact inherited baseline tuple.
#   block_unless_reviewed_inherited_baseline -> UNKNOWN blocks everywhere EXCEPT the image
#                                              path, where an exact inherited baseline tuple
#                                              may accept it (ordinary/app findings still block).
_UNKNOWN_SEVERITY_MODES = {"block", "block_unless_reviewed_inherited_baseline"}


@dataclass(frozen=True)
class VulnPolicy:
    fail_on_severity: str = "high"
    exceptions: dict[str, VulnException] = field(default_factory=dict)
    unknown_severity: str = "block"

    @property
    def threshold_rank(self) -> int:
        return _SEVERITY_RANK[self.fail_on_severity.lower()]

    @property
    def allow_inherited_unknown(self) -> bool:
        return self.unknown_severity == "block_unless_reviewed_inherited_baseline"


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

    Fail-closed but Trivy-accurate: each report MUST be a recognised Trivy report (it
    carries ``SchemaVersion`` — Trivy always emits it). For such a report, ``Results``
    that is absent or ``null`` is a VALID empty scan (Trivy emits ``Results: null`` when a
    target yields no findings, e.g. a directory with no lockfile) and contributes no
    findings; ``Results`` present-but-not-a-list is malformed and raises. A non-object or
    a report WITHOUT ``SchemaVersion`` (e.g. ``{}``, ``{"Results": null}`` from a defaulted
    missing file, or arbitrary JSON) is unrecognised and raises — so a missing/failed scan
    can never be re-wrapped into a clean envelope that bypasses ``assert_scan_evidence``."""
    combined: list[dict[str, Any]] = []
    for index, report in enumerate(reports):
        if not isinstance(report, dict):
            raise SupplyChainViolation(f"Trivy report {index} is not an object")
        if "SchemaVersion" not in report:
            raise SupplyChainViolation(
                f"Trivy report {index} is not a recognised Trivy report (no SchemaVersion)"
            )
        results = report.get("Results")
        if results is None:
            results = []  # a recognised Trivy report with no findings
        if not isinstance(results, list):
            raise SupplyChainViolation(f"Trivy report {index} 'Results' must be a list when present")
        combined.extend(results)
    return {"Results": combined}


def evaluate_scan(
    findings: Iterable[dict[str, Any]],
    policy: VulnPolicy,
    *,
    on: date | None = None,
) -> ScanDecision:
    """Partition scan findings into blocking vs documented-exception, fail-closed.

    This is the ORDINARY policy path (used for the filesystem/app dependency scan): unknown
    severity ALWAYS blocks here and can never be exempted, and only KNOWN severities at or
    above the threshold are eligible for an unexpired documented exception. The ONLY place an
    unknown-severity finding may be accepted is the image base-attribution path
    (evaluate_image_vulnerabilities), and only via an exact reviewed-baseline tuple when the
    policy's unknown_severity mode authorises it — never through an exception here."""
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


# --- base-image risk baseline (inherited-finding attribution) ------------------
#
# A HIGH/CRITICAL image finding may pass ONLY when it is an exact, presently-unfixable
# finding inherited from the reviewed, digest-pinned base image and recorded in the
# reviewed accepted-base-findings baseline. Everything else (app-introduced, fixable,
# new, changed, expired, unknown, base-digest-mismatch) fails closed. This is stronger
# than a blanket `--ignore-unfixed`: the full findings are retained and each acceptance
# is bound to an exact (CVE, package, version, severity, status) tuple + base digest.

_ACCEPTABLE_NOFIX_STATUSES = {"affected", "fix_deferred", "will_not_fix"}


def trivy_vulnerabilities(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalised vulnerability records from a Trivy report (``Results[].Vulnerabilities``).

    ``class``/``type`` come from the enclosing Result (e.g. ``os-pkgs``/``debian`` vs
    ``lang-pkgs``/``python-pkg``) and are part of a finding's identity: they keep an
    OS-package finding from being conflated with a same-named language-package finding."""
    out: list[dict[str, Any]] = []
    if not isinstance(report, dict):
        return out
    for result in report.get("Results") or []:
        r = result or {}
        target, cls, typ = r.get("Target"), r.get("Class"), r.get("Type")
        for v in r.get("Vulnerabilities") or []:
            out.append(
                {
                    "id": v.get("VulnerabilityID"),
                    "package": v.get("PkgName"),
                    "installed_version": v.get("InstalledVersion"),
                    "severity": str(v.get("Severity", "")).lower(),
                    "status": v.get("Status"),
                    "fixed_version": v.get("FixedVersion") or "",
                    "target": target,
                    "class": cls,
                    "type": typ,
                }
            )
    return out


def _finding_key(finding: dict[str, Any]) -> tuple:
    # Identity tuple bound to the reviewed base: CVE, package, version, severity, status,
    # AND the Trivy result class/type (os-pkgs/debian vs lang-pkgs/python-pkg). The raw
    # display target is deliberately excluded — it differs between a by-ref base scan and
    # an OCI-layout image scan, so it is not a stable identity component.
    return (
        finding.get("id"),
        finding.get("package"),
        str(finding.get("installed_version")),
        str(finding.get("severity", "")).lower(),
        finding.get("status"),
        str(finding.get("class", "")).lower(),
        str(finding.get("type", "")).lower(),
    )


def load_base_baseline(mapping: dict[str, Any]) -> dict[str, Any]:
    """Parse the reviewed accepted-base-findings baseline into a lookup.

    Shape: ``base_image: {ref, digest, valid_until}`` + ``accepted_inherited_findings:
    [{id, package, installed_version, severity, status, expires, ...}]``. Each entry
    requires a valid ISO ``expires`` (or falls back to ``base_image.valid_until``); a
    missing/invalid expiry or a malformed digest raises (fail closed)."""
    bi = (mapping or {}).get("base_image") or {}
    digest = str(bi.get("digest", "")).strip()
    if not _BARE_DIGEST_RE.fullmatch(digest):
        raise SupplyChainViolation("base baseline base_image.digest is not a sha256 manifest digest")
    ref = str(bi.get("ref", "")).strip()
    if not ref:
        raise SupplyChainViolation("base baseline base_image.ref is required (must match the pinned base)")
    if not is_digest_pinned(ref):
        raise SupplyChainViolation("base baseline base_image.ref must be digest-pinned (name@sha256:<64 hex>)")
    if manifest_digest_of(ref) != digest:
        raise SupplyChainViolation(
            "base baseline base_image.ref embeds a different digest than base_image.digest "
            f"({manifest_digest_of(ref)} != {digest})"
        )
    default_expiry_raw = bi.get("valid_until")
    entries: dict[tuple, date] = {}
    for raw in (mapping or {}).get("accepted_inherited_findings") or []:
        # class/type are part of the identity (see _finding_key): an accepted tuple must
        # name the Trivy result class/type it was reviewed under, so a same-id/package
        # finding from a different result class cannot inherit its acceptance.
        for field in ("id", "package", "installed_version", "severity", "status", "class", "type"):
            if not str(raw.get(field, "")).strip():
                raise SupplyChainViolation(f"accepted_inherited_findings entry missing '{field}'")
        if str(raw.get("status")) not in _ACCEPTABLE_NOFIX_STATUSES:
            raise SupplyChainViolation(
                f"accepted_inherited_findings status {raw.get('status')!r} is not a no-fix status"
            )
        if raw.get("fixed_version"):
            raise SupplyChainViolation("an accepted inherited finding must have no fixed_version")
        expires_raw = raw.get("expires") or default_expiry_raw
        if not expires_raw:
            raise SupplyChainViolation("accepted_inherited_findings entry requires 'expires' (or base_image.valid_until)")
        try:
            expires = date.fromisoformat(str(expires_raw))
        except ValueError as exc:
            raise SupplyChainViolation(f"accepted_inherited_findings invalid expires: {expires_raw!r}") from exc
        key = _finding_key(raw)
        if key in entries:
            raise SupplyChainViolation(f"duplicate accepted_inherited_findings tuple: {key}")
        entries[key] = expires
    return {"base_digest": digest, "base_ref": ref, "entries": entries}


def assert_base_report_identifies_digest(base_report: dict[str, Any], base_digest: str) -> None:
    """Fail closed unless ``base_report`` actually describes the pinned base digest.

    Binds ``scan.base.json`` to the reviewed digest: Trivy records the scanned image's
    digest in ``ArtifactName`` (when scanned by ``name@sha256:...``) and/or
    ``Metadata.RepoDigests``. If neither carries the expected digest, a substituted base
    report cannot stand in for the reviewed base."""
    bare = str(base_digest).split("sha256:")[-1].lower()
    if not bare:
        raise SupplyChainViolation("no base digest to bind the base scan report to")
    artifact = str((base_report or {}).get("ArtifactName", ""))
    repo_digests = ((base_report or {}).get("Metadata") or {}).get("RepoDigests") or []
    haystack = (artifact + " " + " ".join(str(d) for d in repo_digests)).lower()
    if bare not in haystack:
        raise SupplyChainViolation(
            "base scan report does not identify the pinned base digest "
            f"(ArtifactName/RepoDigests do not contain sha256:{bare})"
        )


@dataclass(frozen=True)
class ImageScanDecision:
    blocking: list[dict[str, Any]]
    accepted_inherited: list[dict[str, Any]]

    @property
    def passed(self) -> bool:
        return not self.blocking


def evaluate_image_vulnerabilities(
    image_report: dict[str, Any],
    base_report: dict[str, Any],
    baseline: dict[str, Any],
    *,
    base_digest: str,
    fail_on_severity: str = "high",
    allow_inherited_unknown: bool = True,
    on: date | None = None,
) -> ImageScanDecision:
    """Attribute every at/above-threshold image finding and decide pass/fail per finding.

    An inherited, presently-unfixable, reviewed-and-unexpired finding is accepted; a
    fixable, app-introduced, non-no-fix-status, base-digest-mismatched, new, or expired
    finding blocks.

    UNKNOWN severity is handled per ``allow_inherited_unknown`` (the policy's
    ``unknown_severity`` mode):
      - False (``block``): UNKNOWN always blocks here, even for an exact inherited tuple.
      - True (``block_unless_reviewed_inherited_baseline``): UNKNOWN is routed through the
        SAME inherited-risk attribution as an at/above-threshold finding, so it is accepted
        ONLY when it is an exact-tuple match in both the standalone base scan and the
        reviewed baseline, unfixable, and unexpired. App-introduced, fixable, or unreviewed
        UNKNOWN still blocks.
    A blanket CVE-id exception can never suppress UNKNOWN (that is the separate
    evaluate_scan path); acceptance is only ever through the explicit, reviewed baseline."""
    today = on or datetime.now(timezone.utc).date()
    threshold = _SEVERITY_RANK[fail_on_severity.lower()]
    base_vulns = trivy_vulnerabilities(base_report)
    base_keys = {_finding_key(f) for f in base_vulns}
    # CVE+package presence in the base (severity-agnostic) — used only to annotate blocking
    # findings so a reviewer can see whether a blocker is inherited from the base or
    # app-introduced, independent of whether its exact tuple matched.
    base_idpkg = {(f.get("id"), f.get("package")) for f in base_vulns}
    bl_digest = baseline.get("base_digest")
    bl_entries: dict[tuple, date] = baseline.get("entries") or {}

    def _block(finding: dict[str, Any], reason: str) -> dict[str, Any]:
        return {**finding, "block_reason": reason, "in_base": (finding.get("id"), finding.get("package")) in base_idpkg}

    blocking: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    for f in trivy_vulnerabilities(image_report):
        rank = _SEVERITY_RANK.get(f["severity"])
        if rank is None:
            # Unknown severity. Under 'block' it is an unconditional block; otherwise it is
            # attributed exactly like an at/above-threshold finding (reviewed-baseline route).
            if not allow_inherited_unknown:
                blocking.append(_block(f, "unknown_severity"))
                continue
        elif rank < threshold:
            continue
        if f["fixed_version"]:
            blocking.append(_block(f, "fix_available"))
            continue
        if f["status"] not in _ACCEPTABLE_NOFIX_STATUSES:
            blocking.append(_block(f, "unknown_or_unacceptable_status"))
            continue
        key = _finding_key(f)
        if key not in base_keys:
            blocking.append(_block(f, "app_introduced"))
            continue
        if bl_digest != base_digest:
            blocking.append(_block(f, "base_digest_mismatch"))
            continue
        if key not in bl_entries:
            blocking.append(_block(f, "not_in_reviewed_baseline"))
            continue
        if bl_entries[key] < today:
            blocking.append(_block(f, "baseline_expired"))
            continue
        accepted.append(f)
    return ImageScanDecision(blocking=blocking, accepted_inherited=accepted)


# --- policy loading + composite release gate ----------------------------------


def policy_from_mapping(mapping: dict[str, Any]) -> VulnPolicy:
    vuln = (mapping or {}).get("vulnerability_policy") or {}
    fail_on = str(vuln.get("fail_on_severity", "high")).lower()
    if fail_on not in _SEVERITY_RANK:
        raise SupplyChainViolation(f"vulnerability_policy.fail_on_severity invalid: {fail_on!r}")
    unknown_severity = str(vuln.get("unknown_severity", "block")).lower()
    if unknown_severity not in _UNKNOWN_SEVERITY_MODES:
        raise SupplyChainViolation(
            f"vulnerability_policy.unknown_severity invalid: {unknown_severity!r} "
            f"(expected one of {sorted(_UNKNOWN_SEVERITY_MODES)})"
        )
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
    return VulnPolicy(fail_on_severity=fail_on, exceptions=exceptions, unknown_severity=unknown_severity)


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
    base_baseline: dict[str, Any] | None = None,
    on: date | None = None,
) -> list[str]:
    """Run every release gate against a manifest; return failure messages (empty == pass).

    The policy's ``require`` flags and ``pinned_base_images`` are CONSUMED here (not
    documentary): a required-but-missing piece of evidence fails closed.

    manifest keys: image_ref (digest, required), dockerfile, sbom, provenance,
    image_scan + base_scan + base_image (vulnerability evidence, base-attributed against
    base_baseline), reproducibility, tools, rollback_ref."""
    failures: list[str] = []
    require = (policy_mapping or {}).get("require") or {}
    pinned_bases = (policy_mapping or {}).get("pinned_base_images")
    pinned_tools = (policy_mapping or {}).get("supply_chain_tools")
    policy = policy_from_mapping(policy_mapping)
    fail_on = policy.fail_on_severity

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
        "reproducibility": require.get("reproducibility_evidence"),
    }
    for manifest_key, is_required in required_map.items():
        if is_required and manifest_key not in manifest:
            failures.append(f"release manifest is missing required '{manifest_key}' evidence")
    if require.get("vulnerability_scan"):
        # fs_scan (the application/dependency filesystem scan) is required evidence too — it
        # is evaluated through the ORDINARY policy below, not the inherited-base baseline.
        for needed in ("image_scan", "base_scan", "base_image", "fs_scan"):
            if needed not in manifest:
                failures.append(f"release manifest is missing required '{needed}' vulnerability evidence")

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
    # Application/dependency filesystem scan — evaluated through the ORDINARY vulnerability
    # policy (exceptions apply; UNKNOWN always blocks), NEVER the inherited-base baseline.
    if "fs_scan" in manifest:
        try:
            fs_report = merge_trivy_reports(manifest["fs_scan"])  # tolerate Trivy's null Results
            assert_scan_evidence(fs_report)
            assert_scan_passes(_scan_findings(fs_report), policy, on=on)
        except SupplyChainViolation as exc:
            failures.append(f"filesystem/dependency scan: {exc}")
    if "image_scan" in manifest and "base_scan" in manifest:
        try:
            assert_scan_evidence(manifest["image_scan"])
            assert_scan_evidence(manifest["base_scan"])
            base_image = manifest.get("base_image") or {}
            base_digest = str(base_image.get("digest", ""))
            base_ref = str(base_image.get("ref", ""))
            # Base ref/digest coherence — fail closed, NO empty-string bypass. The manifest
            # base ref must be a digest-pinned reference that is the policy-pinned base, its
            # embedded digest must equal the manifest digest field, the reviewed baseline must
            # agree on both ref and digest, and scan.base.json must itself identify that
            # digest. This denies a malformed evidence set that presents policy ref A while
            # separately claiming digest B.
            if not is_digest_pinned(base_ref):
                failures.append("manifest base_image.ref must be a digest-pinned reference (name@sha256:<64 hex>)")
            else:
                if pinned_bases and base_ref not in pinned_bases:
                    failures.append(f"manifest base_image.ref {base_ref!r} is not the policy-pinned base")
                ref_digest = manifest_digest_of(base_ref)
                if base_digest != ref_digest:
                    failures.append(
                        f"manifest base_image.digest {base_digest!r} does not match the digest embedded in "
                        f"base_image.ref ({ref_digest})"
                    )
            if base_baseline:
                bl_ref = str(base_baseline.get("base_ref", ""))
                bl_digest = str(base_baseline.get("base_digest", ""))
                if bl_ref != base_ref:
                    failures.append(
                        f"base baseline base_image.ref {bl_ref!r} does not match the manifest base ref {base_ref!r}"
                    )
                if bl_digest != base_digest:
                    failures.append(
                        f"base baseline digest {bl_digest!r} does not match the manifest base digest {base_digest!r}"
                    )
            assert_base_report_identifies_digest(manifest["base_scan"], base_digest)
            decision = evaluate_image_vulnerabilities(
                manifest["image_scan"],
                manifest["base_scan"],
                base_baseline or {"base_digest": None, "base_ref": "", "entries": {}},
                base_digest=base_digest,
                fail_on_severity=fail_on,
                allow_inherited_unknown=policy.allow_inherited_unknown,
                on=on,
            )
            if not decision.passed:
                reasons: dict[str, int] = {}
                for b in decision.blocking:
                    reasons[b.get("block_reason", "?")] = reasons.get(b.get("block_reason", "?"), 0) + 1
                detail = ", ".join(f"{r}={n}" for r, n in sorted(reasons.items()))
                # Per-finding breakdown (id package@version class/type severity status reason
                # in_base), sorted, so a blocked release is diagnosable from the gate output
                # alone (class/type included so a tuple mismatch reveals the actual values).
                lines = sorted(
                    f"{b.get('id')} {b.get('package')}@{b.get('installed_version')} "
                    f"{b.get('class') or '?'}/{b.get('type') or '?'} "
                    f"sev={b.get('severity') or '?'} status={b.get('status') or '?'} "
                    f"reason={b.get('block_reason')} in_base={'Y' if b.get('in_base') else 'N'}"
                    for b in decision.blocking
                )
                failures.append(
                    f"{len(decision.blocking)} unapproved image vulnerability finding(s) at/above "
                    f"'{fail_on}' fail closed ({detail}):\n      "
                    + "\n      ".join(lines)
                )
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
    p_rel.add_argument("--base-baseline", help="accepted-base-findings YAML/JSON (inherited-risk baseline)")
    p_rel.add_argument("--decision-out", help="write a pass_with_accepted_inherited_risk decision summary JSON here")

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
            manifest = _load(args.manifest)
            policy_mapping = _load(args.policy)
            accepted = load_accepted_digests(_load(args.accepted_releases)) if args.accepted_releases else None
            base_baseline = load_base_baseline(_load(args.base_baseline)) if args.base_baseline else None
            failures = evaluate_release(
                manifest, policy_mapping, accepted_digests=accepted, base_baseline=base_baseline
            )
            if failures:
                print(f"FAIL: {len(failures)} supply-chain gate violation(s):", file=sys.stderr)
                for msg in failures:
                    print(f"  - {msg}", file=sys.stderr)
                return 1
            if "image_scan" in manifest and "base_scan" in manifest and base_baseline is not None:
                _policy = policy_from_mapping(policy_mapping)
                decision = evaluate_image_vulnerabilities(
                    manifest["image_scan"], manifest["base_scan"], base_baseline,
                    base_digest=str((manifest.get("base_image") or {}).get("digest", "")),
                    fail_on_severity=_policy.fail_on_severity,
                    allow_inherited_unknown=_policy.allow_inherited_unknown,
                )
                acc = decision.accepted_inherited
                summary = {
                    "scan_decision": "pass_with_accepted_inherited_risk" if acc else "pass_no_findings",
                    "blocking_findings": 0,
                    "accepted_inherited_total": len(acc),
                    "accepted_inherited_high": sum(1 for f in acc if f["severity"] == "high"),
                    "accepted_inherited_critical": sum(1 for f in acc if f["severity"] == "critical"),
                    # Inherited findings upstream has not yet scored (Trivy severity UNKNOWN),
                    # accepted only via an exact reviewed-baseline tuple — surfaced explicitly
                    # so the decision record never silently omits them.
                    "accepted_inherited_unknown": sum(1 for f in acc if f["severity"] == "unknown"),
                    "base_digest": base_baseline.get("base_digest"),
                }
                print(f"OK: supply-chain gates passed ({summary['scan_decision']}): {json.dumps(summary)}")
                if args.decision_out:
                    json.dump(summary, open(args.decision_out, "w"), indent=2)
            else:
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
