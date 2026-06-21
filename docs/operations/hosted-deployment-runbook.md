# Hosted Deployment Runbook

This runbook describes operations, incident response, and deployment/rollback for
OpenVA's **bounded hosted resolver** — the secrets/identity boundary and the
kill-switch — for the architecture recorded in
[ADR-0006](../architecture/decisions/ADR-0006-hosted-public-read-deployment.md)
and governed by [ADR-0001](../architecture/decisions/ADR-0001-hosted-resolver-and-live-verification.md).
Read the [decision report](hosted-deployment-decision.md) (§6 secrets, §10
degradation, §12 delivery/rollback) and the
[contract](contracts/hosted-deployment.yaml) first.

**Decision-only, non-advisory.** Nothing here is provisioned. No infrastructure
exists, no endpoint is live, no provider/region/domain is chosen, and no
production secret exists. Every procedure is written in future framing ("when
provisioned, the operator will"). Output is non-advisory (`not_advice: true`):
OpenVA is public-source-only and metadata-first, and does not provide legal,
compliance, or vendor-risk advice. These limits are unchanged by hosting.

## Environments And Identity Separation

| Environment | Purpose | Secrets / identity | Provisioned? |
| --- | --- | --- | --- |
| development | Local container only; no GitHub App, no cloud identity | Local, throwaway; never the production App | No (local only) |
| staging | Maintainer-owned staging host; full smoke target | Separate App install, separate secret store, separate workload identity | No (when provisioned) |
| production | Maintainer-owned production host; public read path | Separate App install, separate secret store, separate workload identity | No (when provisioned) |

Staging and production never share an App key, a secret store entry, a workload
identity, or a registry credential. Development holds no production-capable
credential. Provider, region, domain, credentials, spend ceiling, production
permissions, and public-traffic enablement are **maintainer-controlled** (human
authority per `GOVERNANCE.md`); none are decided in this work package.

## Deploy Procedure (When Provisioned)

The deployable is a single immutable OCI image built from
`services/openva_match_service/Dockerfile`. CI holds no production secret in the
repo.

1. **Build** an immutable image on tag; record build provenance (SLSA-style
   attestation) and an SBOM. Base images are pinned.
2. **Scan** the image and its dependencies. A scan finding above the agreed
   threshold blocks promotion.
3. **Push** to the provider-native registry with immutable tags; deploys are
   digest-addressed.
4. **Promote staging → production** as a **maintainer-gated** action: the operator
   promotes the *same digest* that passed staging smokes. CI builds, scans, and
   pushes; it never carries a production credential and never auto-promotes.

No registry, secret, or environment is created by following this document; these
steps are the procedure the operator will run after the maintainer accepts the
external decisions in ADR-0006.

## Production Smoke Sequence (Evidence Before Public Traffic)

Run A → B → C against the production host **before** public traffic is enabled.
Record the result of each as launch evidence; public-traffic enablement is a
separate maintainer action that depends on this evidence.

| Step | Check | Pass condition |
| --- | --- | --- |
| A | Health + cached read: `/healthz`, `/readyz`, one cached `/v1` read | All healthy; cached read served `from_cache` with no egress |
| B | One verify job end-to-end with a known vendor | Job reaches `completed`; result returned; **no catalogue write-back** occurs |
| C | Candidate-intake dry-run | Proves the **PR-bound boundary**: a candidate is *proposed* only via the existing PR lifecycle; no `data/**` or `main` write; no merge |

If any step fails, do not enable public traffic. The static layer remains the
serving floor.

## Rollback

| Criterion | Trigger | Action |
| --- | --- | --- |
| SLO breach | Availability/latency/verify-success below the proposed SLOs (decision §9–10) | Roll back to prior digest |
| Security incident | Suspected credential exposure, SSRF/abuse, or boundary violation | Run the credential-revocation sequence (below), then roll back |
| Cost-ceiling breach | Budget alert fires against the engineered ceiling (decision §11) | Kill-switch, then roll back |

**Mechanics:** redeploy the prior immutable image by digest. This is **instant on
Cloud Run / Azure Container Apps** (revision repoint) and an **alias repoint on
AWS Lambda**. Rollback never rebuilds and never edits the running image; it
selects a previously-scanned digest. The static layer keeps serving throughout.

## Kill-Switch

The kill-switch disables `verify` and candidate-ingress **independently of the
read path**. The static/cached layer (GitHub Pages exports + static MCP + pinned
pack) keeps serving because it is independent of the host.

- **Disable verify** → outbound fetch / async jobs stop; reads fall back to
  cached, clearly labelled, never presenting stale as live.
- **Disable candidate-ingress** → no new candidate PRs are proposed; the existing
  PR lifecycle is untouched.
- **Independence:** ingress disablement does not stop read serving, and read
  serving can be disabled without affecting the static layer.
- **Terminal safe state:** *hosted disabled, static layer serving.* This state is
  always reachable and is the recovery target for every incident.

## Secrets And Identity Boundary

| Concern | Rule |
| --- | --- |
| GitHub App key custody | A **stored secret on every platform** — GitHub Apps cannot use OIDC. Lives in a managed secret store (Secret Manager / Key Vault / SSM). |
| Credential isolation | Held/used by **only the candidate-ingress component**. The internet-facing API and the verify worker hold **no** GitHub credential (least-privilege `access_matrix`), so a compromise of the public surface cannot reach the key. |
| Storage prohibition | Never in the repo, browser, build artifacts, or logs. |
| Remote signing | Preferred where the provider supports it (AWS KMS, Azure Key Vault) so the raw key never enters the app. |
| Cloud API access | Provider **workload identity** (keyless); no static cloud keys. This does not remove the GitHub App key. |
| Least privilege | The App is scoped to **contents + pull-requests on the OpenVA repo only** — for candidate-intake PRs. **No merge / no catalogue-merge authority.** The serving process holds read-only catalogue access. |
| Rotation | Rotate the App private key on a schedule and immediately on any suspected exposure; revoke the live installation token first. |
| Staging ≠ production | Separate Apps, secrets, and identities per environment. No cross-environment reuse. |
| Break-glass | Documented revocation: revoke installation token → disable ingress → rotate key (see incident response). |

No secret is created in this work package.

## Incident Response

Standard lifecycle: **detect → contain → eradicate → recover → review.**

1. **Detect** — an alert fires (error-rate, latency, queue-saturation, cost/abuse)
   on a maintainer notification path; correlation is by `job_id` only. No
   `prohibited_telemetry_fields` (request bodies, vendor identity, inventory rows,
   uploaded inventory, tool arguments, candidate URLs) appear in any signal.
2. **Contain** — engage the kill-switch (disable verify + candidate-ingress);
   the static layer keeps serving.
3. **Eradicate** — for a credential incident, run the revocation sequence below.
   For abuse, tighten rate limits / concurrency caps.
4. **Recover** — confirm the terminal safe state, then roll back to the last good
   digest and re-run the smoke sequence before re-enabling public traffic.
5. **Review** — record a post-incident note: trigger, timeline, evidence, and the
   rotation/rollback actions taken.

**Credential-revocation sequence (break-glass):**

1. **Revoke the installation token** (immediate; cuts the live PR-propose path).
2. **Disable ingress** via the kill-switch.
3. **Rotate the GitHub App private key** in the managed secret store.
4. **Roll back the image** to the prior immutable digest.
5. **Confirm the static layer is serving** — the terminal safe state.

## Maintainer Decision Boundary

These external decisions are **maintainer-controlled** (human authority per
`GOVERNANCE.md`) and **none is made in this work package**:

- Provider acceptance
- Region selection
- Domain (maintainer-owned OpenVA host)
- DNS / TLS configuration
- Container registry creation
- Secrets + identity (workload identity; App key in a managed secret store; remote
  signing where available)
- Spend ceiling value (instance/concurrency cap + edge rate limit + budget-alert
  kill-switch — no vendor hard cap exists)
- Production permissions (least-privilege; staging ≠ production)
- Public-traffic enablement (only after staging smokes pass)
- ADR-0006 acceptance — **accepted** (the architecture decision is recorded as
  Accepted; the other decisions above remain pending)

ADR-0006 is now **Accepted** (the architecture decision); the remaining external
decisions above are still maintainer-gated, and acceptance authorises no provisioning
by itself. The rollback posture of ADR-0001 (static layer always serving) remains the
standing safe state.
