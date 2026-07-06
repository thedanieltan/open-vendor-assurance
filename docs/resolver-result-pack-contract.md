# Resolver Result-Pack Contract

The resolver result-pack is the stable output shape for local-first resolver
implementations and static integrations. It lets CLIs, local engines, MCP
servers, forked deployments, GitHub Pages, Lovable, and other consumers build
against a deterministic contract without making OpenVA a hosted resolver,
hosted CSV processor, or operated API runtime.

Operational metadata only. This result pack is not legal, compliance,
procurement, security, KYC, AML, audit, vendor-risk, approval, suitability, or
recommendation advice.

OpenVA owns the shape of the answer, not the runtime that computes it. The
result pack is the product boundary: consumers may run their own live resolver
and emit this contract, but OpenVA does not process user vendor inventories.

## Version

```text
result_pack_version: 1.0.0
```

## Provenance Model

Result packs separate candidate input provenance from verification outcome
provenance. These axes must not be collapsed.

Candidate input basis says why a locator or source candidate was available to
the resolver:

```text
candidate_basis
```

Allowed values:

```text
community_hint
vendor_asserted
cached_locator
direct_input
none
```

Community hints are unverified candidate inputs. Vendor assertions are
unverified candidate inputs. Cached locators are unverified candidate inputs.
Direct user input is also only a candidate input until the consumer environment
performs live verification.

Verification basis says what a consumer-side live resolver run established:

```text
verification_basis
```

Allowed values:

```text
not_checked
verified_live
live_unavailable
live_gated
live_not_found
```

Only a consumer-side live verification run may emit `verified_live`. Static
browser output, community index rows, cached locators, and vendor assertions
must remain `verification_basis=not_checked` unless a separate live check has
actually run in the consumer environment.

The public/community index is hint-only. It is not authoritative evidence and
must not be treated as final truth. Final truth for a result-pack row comes only
from a live resolver run performed by the consumer environment.

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
candidate_basis
verification_basis
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

`status` is the projected outcome, while `candidate_basis` and
`verification_basis` explain how that outcome was reached. A cached URL may be
included as a candidate locator, but the source remains
`status=not_checked`, `candidate_basis=cached_locator`, and
`verification_basis=not_checked` until a consumer-side live check occurs.

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
openva_trust_center_candidate_basis
openva_trust_center_verification_basis
openva_trust_center_checked_at
openva_dpa_status
openva_dpa_url
openva_dpa_candidate_basis
openva_dpa_verification_basis
openva_dpa_checked_at
openva_subprocessors_list_status
openva_subprocessors_list_url
openva_subprocessors_list_candidate_basis
openva_subprocessors_list_verification_basis
openva_subprocessors_list_checked_at
openva_privacy_notice_status
openva_privacy_notice_url
openva_privacy_notice_candidate_basis
openva_privacy_notice_verification_basis
openva_privacy_notice_checked_at
openva_security_page_status
openva_security_page_url
openva_security_page_candidate_basis
openva_security_page_verification_basis
openva_security_page_checked_at
openva_status_page_status
openva_status_page_url
openva_status_page_candidate_basis
openva_status_page_verification_basis
openva_status_page_checked_at
openva_not_advice
```

## Resolver-State Mapping

The Python projection uses `tools/openva/vendor_resolution.py` as the matching
and resolution authority. It does not reimplement matching.

| Resolver state | Result-pack mapping |
| --- | --- |
| `catalog_current` | `status=found` only when `verification_basis=verified_live`; cached/static output MUST use `status=not_checked`, `candidate_basis=cached_locator`, `verification_basis=not_checked` |
| `catalog_refreshed` | `status=found`, `verification_basis=verified_live` only when consumer-side live verification supports the refreshed locator |
| `newly_discovered` | `status=found`, `verification_basis=verified_live` only when consumer-side live discovery and verification support the result |
| `source_unavailable` | `status=unavailable`, `verification_basis=live_unavailable` when consumer-side live evidence supports it |
| `not_found` | `status=not_found`, `verification_basis=live_not_found` when live checking or discovery was actually attempted |
| `identity_ambiguous` | `identity_status=no_match`, `no_match_reason=multiple_plausible_entities` |
| `verification_inconclusive` | `status=gated`, `status=unavailable`, or `status=not_checked` depending on the consumer-side live result; do not overclaim |
| `candidate_processing` | `status=not_checked`, `verification_basis=not_checked` |
| `catalogued` | `status=found` only when live-checked; otherwise `status=not_checked`, `candidate_basis=cached_locator`, `verification_basis=not_checked` |

## Static Honesty Rule

The GitHub Pages browser path is static and cached. It MUST NOT perform live
egress, live source verification, live discovery, candidate lifecycle routing,
server-side CSV upload, or server-side persistence.

For browser-local output:

- emit `identity_status=match` only when the conservative browser-local matcher
  matches a vendor from the loaded static index;
- emit `identity_status=no_match` when the browser-local matcher does not match;
- for every requested source type requiring live verification, emit
  `status=not_checked`, `verification_basis=not_checked`, and `checked_at=null`;
- a known cached URL MAY be included as a locator, but it MUST remain
  `candidate_basis=cached_locator` and `verification_basis=not_checked`;
- community hints and vendor assertions MAY be carried as candidate inputs, but
  they MUST remain unverified unless separately live-verified;
- never emit `verification_basis=verified_live`;
- never emit live `found` semantics.

Consumer-run live resolver surfaces may emit `verification_basis=verified_live`
only after the consumer environment has actually performed the bounded live
verification or discovery path. No source result should imply OpenVA operated
the check.
