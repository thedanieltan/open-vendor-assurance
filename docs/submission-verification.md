# Submission Verification

This document describes how OpenVA verifies source claims filed through the submission issue forms (see `docs/submission-intake.md`).

The verification bot verifies claims; it does not trust them. It classifies a submitted source and records observed facts. It never writes catalog truth, never creates branches or pull requests, never promotes a source, never probes a source the submitter marked as gated, and never bypasses bot protection, login walls, or trust portals. Verification output is source metadata and provenance, not a legal or compliance conclusion.

## What the bot does

For a submission issue, the `submitted-source-verification.yml` workflow:

1. fetches the live issue state (body, title, labels);
2. skips entirely when the issue carries `openva-hold` or carries no `submission:` label — this guard applies to every trigger path, including manual dispatch;
3. parses the form fields;
4. validates URL safety before any fetch (public http/https only; no private, loopback, or otherwise blocked hosts);
5. fetches public sources transparently with an identified user agent, following safe redirects;
6. records HTTP status, final URL, and content type;
7. detects authentication requirements, bot protection, and gated access;
8. compares the final domain against the submitted vendor domain and any matching catalog vendor domains;
9. classifies likely source type consistency, retrieval method, and canonical confidence;
10. detects duplicates of existing canonical catalog sources;
11. writes a verification report artifact, upserts one verification comment on the issue, and applies exactly one `candidate:` triage label.

## Verification results and labels

| Verification result | Triage label | Meaning |
| --- | --- | --- |
| `canonical_candidate` | `candidate:verified` | Public, on the vendor's domain, no redirect, content consistent with the claimed source type. |
| `likely_vendor_published` | `candidate:verified` | Public and on the vendor's domain; canonical location not fully confirmed. |
| `possible_match` | `candidate:needs-review` | Reachable but signals are incomplete or off the claimed domain without a redirect. |
| `duplicate_existing_source` | `candidate:duplicate` | URL already exists as a canonical catalog source. |
| `redirected_ambiguous` | `candidate:ambiguous` | Redirect ended somewhere that cannot be confirmed as the vendor's location. |
| `gated_or_auth_required` | `candidate:gated` | Declared gated by the submitter, or fetch shows login or restricted access. |
| `bot_protected` | `candidate:gated` | Fetch hit bot protection; OpenVA does not bypass it. |
| `source_type_mismatch` | `candidate:ambiguous` | Fetched content contradicts the claimed source type. |
| `unsafe_url` | `candidate:rejected` | URL failed safety checks; it was not fetched. |
| `fetch_failed` | `candidate:fetch-failed` | Unreachable, missing, erroring, or no verifiable URL in the submission. |

`requires_review: false` is set only for `canonical_candidate`, `likely_vendor_published`, and `duplicate_existing_source`. Every other result requires maintainer review. No result auto-promotes anything: catalog data changes only through reviewed pull requests.

## Report fields

The verification comment embeds a machine-readable YAML report with:

```yaml
candidate_source_id:
vendor_id_or_candidate:
submitted_url:
final_url:
http_status:
content_type:
source_type_candidate:
retrieval_method_candidate:
canonical_confidence_candidate:
duplicate_match:
requires_review:
verification_result:
verification_reason:
observed_at:
checks:
not_advice: true
```

Reports record verification-produced facts and enumerable claim fields only. They never echo submitter free text, raw issue bodies, or fetched page content.

## Determinism

Classification is a pure function of the parsed claim and the fetch observations. The report records the observed inputs (`http_status`, `final_url`, `content_type`, `observed_at`, `checks`), so every verdict is reproducible from the report itself. Re-running verification updates the existing bot comment in place.

## Non-advisory reminder

A verification result describes the observed state of a public source reference. It does not mean OpenVA approves, recommends, certifies, scores, or determines whether any vendor is compliant, safe, adequate, suitable, low risk, or high risk.
