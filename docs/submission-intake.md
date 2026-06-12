# Submission Intake

This guide explains how to submit vendor and source claims to OpenVA through GitHub issue forms, and what happens to a submission after it is filed.

A submission is a claim. It does not change catalog data. Claims enter verification before any catalog update, and catalog data changes only through reviewed pull requests. OpenVA records public source metadata and provenance, not legal conclusions.

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
2. A maintainer triages the claim. Submissions that are misfiled or cannot be classified into a type are labeled `submission:needs-triage`.
3. The claim awaits verification. Verification checks the submitted URL, access posture, and classification before any catalog change is proposed.
4. Catalog data changes only through a reviewed pull request. No submission mutates catalog truth directly.

Submitted issues are non-authoritative until verified.

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
