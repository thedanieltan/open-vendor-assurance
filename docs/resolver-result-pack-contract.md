# Resolver Result-Pack Contract

The resolver result-pack is the stable output shape for OpenVA's indexed public assurance source-reference enrichment.

OpenVA populates vendor lists with indexed public assurance source references. It does not operate as a vendor approval, scoring, monitoring, legal, compliance, procurement, audit, security, KYC, AML, sanctions, suitability, or risk-advice product.

The templates for human and agent users are defined in [`output-templates.md`](output-templates.md).

## Product boundary

OpenVA's default answer is based on the loaded OpenVA index.

It should be described as:

```text
indexed public assurance source references
```

Do not describe default output as:

```text
current source references
live checked references
freshly verified references
monitoring results
risk findings
approval findings
```

A blank source URL means OpenVA has no indexed public source reference for that source type in the loaded index. It is not a negative compliance or security finding.

## Human CSV contract

Human CSV output is preset-based.

The default rule is:

```text
original user columns + selected OpenVA enrichment columns
```

OpenVA must preserve the user's original columns where practical and append the selected OpenVA columns. It should not force optional identity fields into the output unless the user supplied them.

### Default human preset: Source URLs

```csv
openva_match,openva_vendor_name,openva_domain,dpa_url,privacy_notice_url,subprocessors_url,security_page_url,trust_center_url,status_page_url,openva_notes
```

### Human identity status

```text
match
no_match
```

If `openva_match=no_match`, OpenVA source URL columns are blank and `openva_notes` should say:

```text
No indexed OpenVA match.
```

### Human presets

The full human preset list is maintained in [`output-templates.md`](output-templates.md):

```text
Source URLs
Privacy / DPA Review
Security Review
Procurement Quick Check
Minimal Match Only
Full Human Export
```

### Human default exclusions

Do not include these fields in default human exports:

```text
match_confidence
catalog_membership
catalog_tier
review_state
freshness_mode
advisory_boundary
candidate_source_count
unavailable_source_count
```

Those fields are diagnostic or internal. They may appear in compatibility or advanced machine exports, but not in the normal spreadsheet template.

## Agent / MCP / API contract

Agent, MCP, and API consumers receive structured rows. The preferred shape is:

```text
input
identity
source_references
notes
not_advice
```

### Agent row template

```json
{
  "row_id": "1",
  "input": {
    "vendor_name": "Stripe",
    "business_entity_name": "",
    "domain": "stripe.com",
    "jurisdiction": "",
    "registration_number": "",
    "registered_address": ""
  },
  "identity": {
    "match_status": "match",
    "matched_vendor_id": "stripe",
    "matched_vendor_name": "Stripe",
    "matched_domain": "stripe.com",
    "match_basis": ["indexed_domain"],
    "no_match_reason": null
  },
  "source_references": {
    "dpa": {
      "status": "indexed",
      "url": "https://stripe.com/legal/dpa",
      "title": "Data Processing Agreement"
    },
    "privacy_notice": {
      "status": "indexed",
      "url": "https://stripe.com/privacy",
      "title": "Privacy Notice"
    },
    "subprocessors": {
      "status": "indexed",
      "url": "https://stripe.com/legal/subprocessors",
      "title": "Subprocessors"
    },
    "security_page": {
      "status": "indexed",
      "url": "https://stripe.com/security",
      "title": "Security"
    },
    "trust_center": {
      "status": "indexed",
      "url": "https://stripe.com/trust",
      "title": "Trust Center"
    },
    "status_page": {
      "status": "not_indexed",
      "url": null,
      "title": null
    }
  },
  "notes": [
    "Matched by indexed domain.",
    "Source references are indexed public references, not vendor approval or risk advice."
  ],
  "not_advice": true
}
```

### Agent identity status

```text
match
no_match
```

Ambiguity is not a third top-level identity status. It is represented as:

```json
{
  "match_status": "no_match",
  "no_match_reason": "multiple_plausible_entities"
}
```

### Agent source-reference status

```text
indexed
not_indexed
gated
unavailable
not_applicable
```

Use `indexed` when OpenVA has an indexed public source reference in the loaded index. Use `not_indexed` when the loaded index has no public source reference for that source type.

### Agent no-match example

```json
{
  "row_id": "2",
  "input": {
    "vendor_name": "Unknown Vendor",
    "domain": ""
  },
  "identity": {
    "match_status": "no_match",
    "matched_vendor_id": null,
    "matched_vendor_name": null,
    "matched_domain": null,
    "match_basis": [],
    "no_match_reason": "no_indexed_openva_match"
  },
  "source_references": {},
  "notes": ["No indexed OpenVA match."],
  "not_advice": true
}
```

## Compatibility projection

Older machine surfaces may continue to expose:

```text
match
sources
primary_source_by_type
source_urls_by_type
```

Those fields are compatibility projections for agents and adapters. They are not the default human spreadsheet template.

Compatibility mapping:

| Compatibility value | Preferred identity value |
| --- | --- |
| `matched` | `match` |
| `ambiguous` | `no_match` with `no_match_reason=multiple_plausible_entities` |
| `no_match` | `no_match` with `no_match_reason=no_indexed_openva_match` |

## Source type keys

Use these human/agent presentation keys:

```text
dpa
privacy_notice
subprocessors
security_page
trust_center
status_page
```

Where the internal source type is `subprocessors_list`, the human and agent presentation key may be `subprocessors`.

## Non-advisory rule

Every result must remain factual and non-advisory.

OpenVA result packs must not state that a vendor is:

```text
approved
recommended
compliant
safe
certified
adequate
suitable
low risk
high risk
```

OpenVA returns indexed public source references only.
