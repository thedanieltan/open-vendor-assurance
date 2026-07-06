# Resolver Result-Pack Contract

The resolver result-pack is the stable output shape for resolver-first browser
and static integrations. It lets Lovable, GitHub Pages, and other static
consumers build against a deterministic contract without enabling live browser
egress, the WP-02C worker, production deployment, or changes to the pinned
agent-export `schema_version: 0.1.0` contract.

Operational metadata only. This result pack is not legal, compliance,
procurement, security, KYC, AML, audit, vendor-risk, approval, suitability, or
recommendation advice.

## Version

```text
result_pack_version: 1.0.0
```

## JSON Rows

A JSON result pack is an array with one object per requested vendor. Row order
MUST preserve input order. Each row has these top-level fields:

```text
result_pack_version
input_index
input_vendor_name
input_domain
identity_status
no_match_reason
matched_vendor_id
matched_vendor_name
sources
not_advice
```

`identity_status` is one of:

```text
match
no_match
```

`no_match_reason` is `null` for matched rows and otherwise one of:

```text
not_in_reference
multiple_plausible_entities
no_public_identity
inconclusive
```

`sources` is a deterministic array ordered as:

```text
trust_center
dpa
subprocessors_list
privacy_notice
security_page
status_page
```

Each source object has:

```text
source_type
status
url
basis
checked_at
```

`status` is one of:

```text
found
not_found
gated
unavailable
not_applicable
not_checked
```

`basis` is one of:

```text
cached
live
```

## Flat CSV

The flat CSV output preserves input row order and appends deterministic columns
after the input columns:

```text
openva_identity_status
openva_no_match_reason
openva_matched_vendor_id
openva_matched_vendor_name
openva_trust_center_status
openva_trust_center_url
openva_trust_center_basis
openva_trust_center_checked_at
openva_dpa_status
openva_dpa_url
openva_dpa_basis
openva_dpa_checked_at
openva_subprocessors_list_status
openva_subprocessors_list_url
openva_subprocessors_list_basis
openva_subprocessors_list_checked_at
openva_privacy_notice_status
openva_privacy_notice_url
openva_privacy_notice_basis
openva_privacy_notice_checked_at
openva_security_page_status
openva_security_page_url
openva_security_page_basis
openva_security_page_checked_at
openva_status_page_status
openva_status_page_url
openva_status_page_basis
openva_status_page_checked_at
openva_not_advice
```

## Resolver-State Mapping

The Python projection uses `tools/openva/vendor_resolution.py` as the matching
and resolution authority. It does not reimplement matching.

| Resolver state | Result-pack mapping |
| --- | --- |
| `catalog_current` | `status=found` only when `basis=live`; cached/static output MUST use `status=not_checked` |
| `catalog_refreshed` | `status=found`, `basis=live` |
| `newly_discovered` | `status=found`, `basis=live` |
| `source_unavailable` | `status=unavailable` when live evidence supports it |
| `not_found` | `status=not_found` when live checking or live discovery was actually attempted |
| `identity_ambiguous` | `identity_status=no_match`, `no_match_reason=multiple_plausible_entities` |
| `verification_inconclusive` | `status=not_checked` or `status=unavailable` depending on available evidence; do not overclaim |
| `candidate_processing` | `status=not_checked` |
| `catalogued` | `status=found` only when live-checked; otherwise `status=not_checked`, `basis=cached` |

## Static Honesty Rule

The GitHub Pages browser path is static and cached. It MUST NOT perform live
egress, live source verification, live discovery, candidate lifecycle routing,
or server-side persistence.

For browser-local output:

- emit `identity_status=match` only when the conservative browser-local matcher
  matches a vendor from the loaded static index;
- emit `identity_status=no_match` when the browser-local matcher does not match;
- for every requested source type requiring live verification, emit
  `status=not_checked`, `basis=cached`, and `checked_at=null`;
- a known cached URL MAY be included as a locator, but it MUST remain
  `basis=cached` and `status=not_checked`;
- never emit `basis=live`;
- never emit live `found` semantics.

The live resolver and future worker surfaces may emit `basis=live` only after
the resolver has actually performed the bounded live verification or discovery
path.
