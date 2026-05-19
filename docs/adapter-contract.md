# Adapter Contract

OpenVA adapters import public metadata packs. The contract below defines the supported inputs and the meaning of exported record groups.

## Allowed Inputs

Supported inputs:

```text
openva-pack.json
indexes/candidate-sources.json
indexes/vendor-search.json
indexes/source-coverage.json
indexes/unavailable-sources.json
dist/vendors/{vendor_id}.json
```

Consumers should discover paths through `openva-pack.json`.

## Record Semantics

`canonical_sources` are accepted OpenVA public metadata references.

`candidate_sources` are non-canonical review candidates.

`unavailable_sources` are reviewed absence or omission records. They are not negative conclusions about a vendor.

`observations` and source verification reports are fetch-time facts. They are not source validity, legal, compliance, procurement, security, or risk determinations.

## Status Mapping

`source_verification.verification_status` is a maintenance diagnostic. `observation.result` is a durable observation record value. Consumers may map both into local operational states while preserving the source metadata boundary.

| Verification status | Import meaning |
| --- | --- |
| `ok` | Source was fetchable during verification. |
| `redirected` | Source redirected; canonical metadata updates require review. |
| `not_found` | Source returned 404 during verification. |
| `gone` | Source returned 410; maintainer review is required. |
| `server_error` | Vendor or server error; retry or review later. |
| `client_error` | Generic 4xx response; review if persistent. |
| `rate_limited` | Automation was throttled. |
| `gated_or_login_required` | Evidence suggests login or access gating; human review is required. |
| `bot_protected` | WAF, CAPTCHA, or challenge-like behavior was encountered. |
| `forbidden_unknown` | Plain forbidden response with insufficient evidence to classify the access state. |
| `homepage_or_generic_redirect` | URL may no longer point to the intended source; review. |
| `possible_mismatch` | Fetched content did not match the expected source type; review. |
| `suspect_inferred_url` | URL appears guessed or template-derived; review. |
| `unreachable` | Network failure; retry or review. |

`403`, `bot_protected`, `fetch_failed`, `rate_limited`, and `forbidden_unknown` are automation or fetch states. They are not source-removal decisions.

## Interpretation Boundary

Tenant-specific reviews, approvals, control mappings, obligation impact, risk decisions, and private evidence remain downstream responsibilities. OpenVA exports public metadata only.
