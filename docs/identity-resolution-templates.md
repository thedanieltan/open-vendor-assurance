# Compact identity-resolution templates

OpenVA should keep human and agent templates compact. Entity-resolution evidence can be rich internally, but default import/export surfaces should expose only the operational result a user or agent needs.

This document records the template boundary behind issue #570.

## Design rule

```text
specific input -> resolved entity when evidence is consistent
vague brand input -> matched brand plus evidence-bounded entity candidates
```

A registration number verifies a specific legal entity. It does not collapse a global brand into one legal entity or one contracting party for every customer.

## Input template boundary

The shared input row remains deliberately small:

```text
row_id
vendor_name
domain
business_entity_name
registration_number
```

Do not add resolver internals to the input template. Users and agents should not have to submit fields such as official-source ids, corroborating-source ids, candidate scores, registry classes, evidence digests, or conflict diagnostics.

## Human default output

Human-facing exports should prefer a small operational projection:

```csv
submitted_name,matched_vendor,entity_status,resolved_entity,jurisdiction,next_action
Stripe,Stripe,ambiguous,,US/IE/UK,Provide contracting entity or registration number
Wise,Wise,resolved,Wise Payments Limited,GB,None
```

The human default answer should make the next action obvious. It should not expose the full evidence-quorum machinery unless a user asks for provenance or diagnostics.

## Agent default output

Agent-facing outputs may include the optional compact `entity_resolution` block:

```yaml
matched_vendor_id: stripe
identity:
  match_status: match
  matched_vendor_id: stripe
  matched_vendor_name: Stripe
entity_resolution:
  status: ambiguous
  matched_entity_id: null
  candidate_entity_ids:
    - stripe-inc
    - stripe-payments-europe-limited
  review_required: true
  reason_code: brand_only_multiple_entities
```

The block is intentionally small:

- `status`
- `matched_entity_id`
- `candidate_entity_ids`
- `review_required`
- `reason_code`

It must not embed full evidence. Agents can dereference ids or request a diagnostic profile when they need more.

## Diagnostic profile

Evidence-quorum internals belong in a diagnostic/provenance profile, not the default templates:

```yaml
diagnostic:
  official_source_ids:
    - wise-payments-limited-companies-house
  corroborating_source_ids:
    - wise-privacy-notice
  conflict_status: none
  quorum_status: passed
```

Diagnostics may explain why a candidate passed, failed, or remained ambiguous. They are not required for ordinary spreadsheet, CSV, MCP, or API consumers.

## Evidence-quorum boundary

For legal-entity registration-number population, OpenVA may promote a scoped entity record when there is:

1. one official source;
2. one corroborating public source; and
3. no material conflict.

This replaces manual legal review only for entity-number population. It does not assert legal advice, vendor approval, procurement approval, vendor-risk conclusion, sanctions/KYC outcome, or the user's contracting party unless that role is separately source-backed.

## Global-brand boundary

A global brand may map to multiple legal entities. The safe default is:

- brand match can be resolved independently;
- legal-entity resolution is scoped to a specific entity id;
- vague brand-only input returns candidate entity ids when multiple evidenced entities exist;
- specific identifiers should resolve to one entity only when evidence is consistent;
- contracting jurisdiction/role should remain unset unless source-backed.

## Anti-bloat rule

Do not expand every template to carry every evidence detail. Default outputs expose the result of resolution, not the whole resolution machinery.
