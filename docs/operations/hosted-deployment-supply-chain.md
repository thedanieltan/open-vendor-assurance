# Hosted deployment — artifact & supply-chain controls (WP-02E)

The deployment-artifact supply-chain controls for the hosted match service, governed by
[ADR-0001](../architecture/decisions/ADR-0001-hosted-resolver-and-live-verification.md)
(product posture) and
[ADR-0006](../architecture/decisions/ADR-0006-hosted-public-read-deployment.md)
(deployment architecture).

**Decision-only / not provisioned.** Nothing here deploys, provisions, or publishes. No
container registry is created, no cloud resource is provisioned, no paid publication
occurs, no staging or production deployment happens, and **no hosted OpenVA endpoint is
live**. The decision-only posture in
[`contracts/hosted-deployment.yaml`](contracts/hosted-deployment.yaml) is unchanged
(`hosted_endpoint_live: false`). OpenVA stays non-advisory (`not_advice`),
public-source-only, and metadata-first.

## What this slice adds

- A fail-closed **policy gate** — `openva_match_service.supply_chain` (a pure, unit-tested
  module + thin CLI). It *evaluates artifact evidence only*; it never builds, pushes,
  provisions, or deploys.
- A declarative policy — [`services/openva_match_service/supply-chain-policy.yaml`](../../services/openva_match_service/supply-chain-policy.yaml).
- A manually-dispatched workflow — [`.github/workflows/release-image.yml`](../../.github/workflows/release-image.yml)
  that builds the artifact, produces the evidence, runs the gate, and retains the
  evidence as CI artifacts. It is **read-only** (`contents: read`, `actions: read`) and
  pushes nothing.

## Controls (all fail closed)

| Control | Rule | Enforced by |
| --- | --- | --- |
| Immutable artifact reference | the deployable reference MUST be `name@sha256:<digest>`; mutable tags (`:latest`, `:v1`, untagged) are rejected | `assert_immutable_image_ref` / `check-image-ref` |
| Pinned base image | every Dockerfile `FROM` must be digest-pinned (`scratch` exempt); pins mirror `supply-chain-policy.yaml` | `assert_dockerfile_base_pinned` / `check-dockerfile` |
| SBOM | a CycloneDX/SPDX SBOM must be present and non-empty | `assert_sbom_present` |
| Build provenance | an in-toto/SLSA attestation must be present and bind the artifact digest | `assert_provenance_present` |
| Vulnerability scan | dependency + image findings at/above `fail_on_severity` (and any **unknown** severity) fail the release unless covered by a documented, unexpired exception | `evaluate_scan` / `assert_scan_passes` |
| Reproducibility / equivalence | rebuild with the same pinned inputs and assert package-set equivalence | `release-image.yml` reproducibility step |
| Rollback | a rollback target must itself be a prior accepted immutable digest | `assert_rollback_target` |

The authoritative release decision is the composite `check-release` gate over a release
manifest (`{image_ref, dockerfile, sbom, provenance, scan, rollback_ref?}`); its non-zero
exit blocks the release.

## Vulnerability-exception handling

A finding that would otherwise block may be exempted only by an explicit entry under
`vulnerability_policy.exceptions` in `supply-chain-policy.yaml`:

```yaml
exceptions:
  - id: CVE-2026-0001        # the scanner's vulnerability id
    reason: "no upstream fix; not reachable in the hosted code path"
    expires: 2026-12-31      # required-by-convention; an expired exception stops suppressing
```

Rules, enforced by code (not just documented):

- an exception suppresses a finding **only while unexpired** (`on <= expires`);
- an **expired** exception does not suppress its finding and is surfaced in the decision
  (`expired_exceptions`), so the allowlist cannot rot silently;
- an exception with no `reason` is rejected;
- an **unknown severity** is never exempted by threshold — it always blocks.

Adding or extending an exception is a reviewed change to `supply-chain-policy.yaml`.

## Reproducibility / equivalence evidence

Full bit-for-bit OCI reproducibility is constrained by the upstream base image and
build-time metadata. This repository therefore asserts, on top of **fully digest-pinned
inputs** (base image + build context), **package-set equivalence**: the workflow rebuilds
the image with the same pinned inputs and `SOURCE_DATE_EPOCH`, regenerates the SBOM, and
fails closed if the rebuilt package set differs (`reproducibility-report.json`).

## Rollback

Rollback is by a **prior accepted immutable digest** — never by re-tagging or by a
mutable reference. The workflow records the built digest and validates an optional
`rollback_ref` input through the same digest rule, so a prior artifact can be re-selected
without a rebuild.

## Artifact retention

`release-image.yml` uploads the SBOM, provenance attestation, scan reports, the release
manifest, and the reproducibility report as CI artifacts with `retention-days: 90`
(`artifact_retention_days` in the policy).

## Explicit non-goals (the WP-02E boundary)

No registry creation, no cloud resource provisioning, no paid publication, no staging or
production deployment, and no claim that a hosted endpoint is live. Keyless signing of the
provenance attestation and registry publication are added with the provisioned registry at
WP-02F/02G (they require an OIDC `id-token` and a registry the maintainer authorises).
