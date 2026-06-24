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
| Immutable OCI manifest digest | the deployable reference is `name@sha256:<digest>` taken from BuildKit `containerimage.digest` (the OCI manifest digest, **not** the local `docker .Id` config id); mutable tags (`:latest`, `:v1`, untagged) are rejected | `assert_immutable_image_ref` + `release-image.yml` OCI build |
| Pinned base image | every Dockerfile `FROM` must be digest-pinned **and** present in the policy's `pinned_base_images` list (`scratch` exempt) | `assert_dockerfile_base_pinned` / `check-dockerfile --policy` |
| SBOM | a CycloneDX/SPDX SBOM must be present and non-empty | `assert_sbom_present` |
| Build provenance | an in-toto/SLSA attestation must be present and bind the artifact's manifest digest | `assert_provenance_present` |
| Vulnerability scan (fail-closed evidence) | the scan report must be a recognised, well-typed envelope (a missing/`{}`/malformed report is rejected, never normalised to zero findings); the scanners run with **no `\|\| true`** | `assert_scan_evidence` + `release-image.yml` |
| Vulnerability policy | findings at/above `fail_on_severity` fail unless covered by a documented unexpired exception; **unknown severity always blocks and can never be exempted** | `evaluate_scan` / `assert_scan_passes` |
| Reproducibility | rebuild from the same pinned inputs and require **OCI manifest digest equality** (digest-to-digest); package-set equivalence is supplementary | `assert_reproducibility_evidence` |
| Pinned + checksum-verified tooling | Syft/Trivy are downloaded as **versioned release archives** from immutable URLs and verified against reviewed-literal SHA-256 digests (`sha256sum -c`) **before execution** — never a mutable `main` installer piped into a shell; the gate (`assert_tool_identity`) requires the recorded `{version, archive_sha256}` to match the policy | `supply_chain_tools` in the policy + `assert_tool_identity` + `release-image.yml` |
| Strict raw-scan merge | the workflow combines the raw Trivy reports via `merge_trivy_reports`, which rejects a missing/`null`/non-list `Results` instead of coercing it to `[]` (so a malformed raw report can't become a clean envelope) | `merge_trivy_reports` |
| Rollback | a rollback target must be an immutable digest **whose manifest digest is in the accepted-release ledger**; syntax alone is rejected | `assert_rollback_target` + `accepted-releases.yaml` |

The authoritative release decision is the composite `check-release` gate over a release
manifest (`{image_ref, dockerfile, sbom, provenance, scan, reproducibility, rollback_ref?}`),
run **only after every piece of evidence exists**. The gate CONSUMES the policy — its
`require.*` flags and `pinned_base_images` are enforced, not documentary — and its non-zero
exit blocks the release.

## Vulnerability-exception handling

A finding that would otherwise block may be exempted only by an explicit entry under
`vulnerability_policy.exceptions` in `supply-chain-policy.yaml`:

```yaml
exceptions:
  - id: CVE-2026-0001        # the scanner's vulnerability id
    reason: "no upstream fix; not reachable in the hosted code path"
    expires: 2026-12-31      # REQUIRED ISO date; an expired exception stops suppressing
```

Rules, enforced by code (not just documented):

- every exception **requires** `id`, `reason`, and a valid ISO `expires` date — a missing
  or invalid `expires` is rejected at load time, so an exception can never be permanent;
- duplicate exception ids are rejected;
- an exception suppresses a finding **only while unexpired** (`on <= expires`);
- an **expired** exception does not suppress its finding and is surfaced in the decision
  (`expired_exceptions`), so the allowlist cannot rot silently;
- an **unknown severity always blocks and can never be exempted** — exceptions apply only
  to known severities at/above the threshold.

Adding or extending an exception is a reviewed change to `supply-chain-policy.yaml`.

## Reproducibility evidence

The **primary** reproducibility proof is **OCI manifest digest equality**: the workflow
builds the image twice from the same fully digest-pinned inputs (base image + build
context) with `--output type=oci,rewrite-timestamp=true` and `SOURCE_DATE_EPOCH`, and the
gate (`assert_reproducibility_evidence`) fails closed unless the two OCI manifest digests
are identical. Package-set equivalence (from the two SBOMs) is retained as **supplementary**
evidence only — it is not a substitute, because identical package sets can still hide
differing layers/config/entrypoint. If the digests do not reproduce, the fix is to the
Dockerfile/build inputs, not to weaken the criterion. The full record is
`reproducibility-report.json` (`manifest_digest`, `rebuild_manifest_digest`,
`digests_match`, `equivalent`, package counts, pinned tool versions).

## Rollback

Rollback is by a **prior accepted immutable digest** — never by re-tagging or by a mutable
reference. `assert_rollback_target` requires the `rollback_ref` to be an immutable digest
**and** for its manifest digest to appear in the accepted-release ledger
([`accepted-releases.yaml`](../../services/openva_match_service/accepted-releases.yaml)).
Digest syntax alone is rejected, and the ledger is empty until a release completes
acceptance review, so rollback **fails closed** until a prior accepted release exists.

## Artifact retention

`release-image.yml` uploads the OCI artifact + BuildKit metadata, both SBOMs, the
provenance attestation, both scan reports, the release manifest, and the reproducibility
report as CI artifacts with `retention-days: 90` (`artifact_retention_days` in the policy).

## Explicit non-goals (the WP-02E boundary)

No registry creation, no cloud resource provisioning, no paid publication, no staging or
production deployment, and no claim that a hosted endpoint is live. Keyless signing of the
provenance attestation and registry publication are added with the provisioned registry at
WP-02F/02G (they require an OIDC `id-token` and a registry the maintainer authorises).
