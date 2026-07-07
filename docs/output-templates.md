# OpenVA Output Templates

OpenVA populates vendor lists with indexed public assurance source references.

This document is the product-level output contract for human spreadsheet users and agent/MCP/API users. OpenVA does not approve, score, monitor, or assess vendors.

## Human spreadsheet exports

Human exports are preset-based.

OpenVA preserves the user's original input columns and appends only the OpenVA columns selected by the preset. OpenVA must not force optional identity columns such as `business_entity_name`, `jurisdiction`, `registration_number`, or `registered_address` into the output unless the user's file already contained them.

### Human status values

`openva_match` is one of:

```text
match
no_match
```

If `openva_match=no_match`, the OpenVA source URL columns are blank and `openva_notes` should say:

```text
No indexed OpenVA match.
```

A blank source URL means OpenVA has no indexed public source reference for that source type in the loaded index. It is not a compliance, security, risk, procurement, or legal conclusion.

### Preset: Source URLs

Default preset for most CISO, DPO, procurement, and vendor-review users.

```csv
openva_match,openva_vendor_name,openva_domain,dpa_url,privacy_notice_url,subprocessors_url,security_page_url,trust_center_url,status_page_url,openva_notes
```

### Preset: Privacy / DPA Review

```csv
openva_match,openva_vendor_name,openva_domain,dpa_url,privacy_notice_url,subprocessors_url,trust_center_url,openva_notes
```

### Preset: Security Review

```csv
openva_match,openva_vendor_name,openva_domain,security_page_url,trust_center_url,status_page_url,openva_notes
```

### Preset: Procurement Quick Check

```csv
openva_match,openva_vendor_name,openva_domain,trust_center_url,privacy_notice_url,security_page_url,openva_notes
```

### Preset: Minimal Match Only

```csv
openva_match,openva_vendor_name,openva_domain,openva_notes
```

### Preset: Full Human Export

```csv
openva_match,openva_vendor_id,openva_vendor_name,openva_domain,openva_match_basis,dpa_url,privacy_notice_url,subprocessors_url,security_page_url,trust_center_url,status_page_url,openva_notes
```

### Do not include by default

These fields are diagnostic or internal and should not appear in default human exports:

```text
business_entity_name
jurisdiction
registration_number
registered_address
match_confidence
catalog_membership
catalog_tier
review_state
freshness_mode
advisory_boundary
candidate_source_count
unavailable_source_count
```

Input identity fields may still be preserved if the user supplied them in the original file.

## Agent / MCP / API output

Agents receive structured rows. The agent may then write selected fields back into Sheets, Notion, Jira, a GRC tool, a procurement system, or another user-controlled workspace.

Top-level envelope:

```json
{
  "index_snapshot": {
    "snapshot_id": "openva-index-YYYY-MM-DD",
    "generated_at": "YYYY-MM-DDTHH:MM:SSZ",
    "advisory_boundary": "non_advisory",
    "content_scope": "indexed_public_source_references_only"
  },
  "rows": []
}
```

Per-row template:

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

### Agent identity status values

```text
match
no_match
```

Ambiguous identity does not become a third top-level status. It is represented as:

```json
{
  "match_status": "no_match",
  "no_match_reason": "multiple_plausible_entities"
}
```

### Agent source-reference status values

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

Older adapters may still expose diagnostic fields such as `match.status`, `sources`, `primary_source_by_type`, or `source_urls_by_type`. Those fields are compatibility projections for machine users and must not drive the default human export.

Compatibility mappings:

```text
matched -> identity.match_status=match
ambiguous -> identity.match_status=no_match, no_match_reason=multiple_plausible_entities
no_match -> identity.match_status=no_match, no_match_reason=no_indexed_openva_match
```
