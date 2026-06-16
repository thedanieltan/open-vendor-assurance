# Submission Intake

This guide explains how to submit vendor and source claims to OpenVA through GitHub issue forms, and what happens to a submission after it is filed.

> **You often do not need this form.** Running the unified resolver in `verify`
> mode (`resolve_vendor_sources` / `resolve_inventory`, see
> `docs/vendor-resolution.md`) durably routes unmatched vendors and stale/missing
> sources into this same autonomous lifecycle automatically, via the
> `maintenance/candidates` queue. The hosted browser Local Matcher is cached-only
> and does **not** route candidates. GitHub issue forms remain available for
> manual claims, but routine unmatched vendors resolved in `verify` mode do not
> require one.

A submission is a claim. It does not change catalog data directly. Claims enter
verification, then the **same autonomous lifecycle** the bot-discovered
candidates use: a verified submission becomes a normalised candidate record
(`schemas/openva/candidate-record.schema.json`, origin `human_submission`),
its eligibility is decided by the shared evaluator, and an eligible vendor is
materialised as `machine_provisional` through a one-vendor pull request, observed,
and promoted by an independent machine quorum. No human approval is required for
a routine catalog record; when evidence is insufficient the submission fails
closed to `deferred` or `rejected`.

OpenVA records public source metadata and provenance, not legal conclusions.

## Submission rules

- Submit public sources only. Public means accessible without login, credentials, NDA, customer status, sales approval, private portal access, support ticket access, or anti-bot bypass.
- Do not upload confidential reports.
- Do not paste SOC reports, DPA contents, customer portal content, or any non-public document. This includes screenshots, copied document text, document hashes of gated content, and summaries of gated content.
- Gated sources must be marked as gated. Use the `Public access confirmed` field. OpenVA may record that a gated source exists; it never records gated contents.
- Do not include advisory wording. A submission states what a vendor publishes, not whether the vendor is approved, recommended, compliant, suitable, safe, adequate, low risk, or high risk.

## Which form to use

| Use case | Use this form |
|---|---|
| Existing catalog correction expected to enter the agent PR lane | Vendor catalog update |
| New source claim for later verification | New assurance source |
| New vendor not yet in OpenVA | New vendor candidate |
| Broken, moved, gated, or retired existing source | Broken or moved source |
| Vendor rename or domain change | Vendor rename or domain change |
| RSS, API, llms.txt, MCP, or sitemap surface | Machine-readable source surface |
| Subprocessor-update feed specifically | New subprocessor update feed |

If unsure, use `New assurance source`. If unsure whether something is in scope at all, use `Scope or boundary question` first.

The `Vendor catalog update` form is the existing correction lane handled by the contribution intake agent. The submission forms in this guide are a separate claims lane: they collect candidate claims for later verification and do not enter the catalog-agent lane.

## What happens to a submission

1. The form applies `status:needs-triage` plus a `submission:` routing label.
2. Routing is automatic from the form labels; misfiled or unclassifiable submissions are labeled `submission:needs-triage`. Maintainers do not gate routine submissions.
3. The submission verification bot checks the submitted URL(s), access posture, and classification, comments a verification summary on the issue, and applies one `candidate:` triage label (for example `candidate:verified`, `candidate:gated`, `candidate:duplicate`). See `docs/submission-verification.md`. Verification does not change catalog data.
4. For a new-vendor submission the bridge (`tools/openva/submission_bridge.py`) verifies **every** supplied assurance URL individually and emits one candidate record. An eligible candidate enters the machine-provisional lane autonomously; a `deferred_*` or `rejected_*` candidate fails closed. A single idempotent lifecycle comment (`tools/openva/submission_lifecycle.py`) tracks the issue and closes it automatically at a terminal state.
5. Catalog data still changes only through a pull request — but that pull request is opened, gated, and merged autonomously, not by a human approval step.

Submitted issues are non-authoritative until the catalog pull request merges.

## How form fields map to source-registry fields

Form fields collect candidate values for the source-registry axes defined in `docs/architecture/SOURCE_REGISTRY_SCHEMA_V1.md`:

| Form field | Source-registry axis |
|---|---|
| Vendor name, Vendor domain | vendor identity (`official_domains`) |
| Previous vendor name, Previous vendor domain | vendor identity history (`display_aliases`, `previous_domains`) |
| Source URL | `source_url` |
| Source type | `source_type` |
| Canonical location belief | `canonical_confidence.class` |
| Observed state | `source_health.status` |
| Public access confirmed | `access_class` and gated marking |
| Machine-readable surface | `retrieval.method` and `retrieval.machine_readable` |
| Why this is authoritative | `source_authority_class` evidence |

`Machine-readable surface` is contributor-facing shorthand (`none`, `rss`, `sitemap`, `llms_txt`, `openapi`, `mcp`, `api`). Verification maps it to the registry `retrieval.method` vocabulary; contributors are not asked to distinguish API flavors precisely.

## Routing labels

```text
submission:new-vendor
submission:new-source
submission:broken-source
submission:vendor-identity
submission:machine-readable
submission:needs-triage
```

`submission:needs-triage` is applied manually by maintainers to submissions that are misfiled or cannot be classified into a type. The other labels are applied automatically by the forms. See `docs/triage-policy.md` for the full label taxonomy.

## Non-advisory reminder

OpenVA records public-source metadata and provenance. A submission, a verification result, or a catalog record does not mean OpenVA approves, recommends, certifies, scores, or determines whether any vendor is compliant, safe, adequate, suitable, low risk, or high risk.
