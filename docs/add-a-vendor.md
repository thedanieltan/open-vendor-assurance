# Add a Vendor

This guide describes the minimum workflow for adding a public vendor assurance record.

## 1. Confirm the source is public

Only use sources that are accessible without:

- login;
- credentials;
- NDA;
- customer status;
- sales approval;
- support ticket access;
- private portal access;
- anti-bot bypass.

If the source is gated, do not add it.

## 2. Create the vendor directory

Use the canonical layout:

```text
data/vendors/{vendor_id}/
  vendor.yaml
  sources/{source_id}.yaml
  artifacts/{artifact_id}.yaml
```

Use lowercase hyphenated IDs.

## 3. Add `vendor.yaml`

The vendor profile should describe the vendor identity and official public domains only.

Do not include private customer-specific notes or risk conclusions.

## 4. Add source records

A source record describes a public page or public document location.

Each source must include:

- `source_id`
- `vendor_id`
- `source_type`
- `source_url`
- `source_language`
- `access_class`
- `rights_class`
- factual summaries
- provenance
- `not_advice: true`

### Source role coverage claims

`source_type` is the primary classification of the public location.

`coverage_claims` records additional explicit source roles evidenced by that same location.

Rules:

1. One public URL should normally have one source record.
2. Do not duplicate `source_url` just to represent multiple roles.
3. Use `coverage_claims` when one source explicitly contains, links to, or references multiple source roles.
4. Do not infer coverage from broad page titles such as trust center, security, legal, or compliance.
5. If the page links to a distinct public stable URL, prefer adding that linked URL as a separate source record when appropriate.
6. `coverage_claims` must stay factual and non-advisory.

Example for a clumped legal page:

```yaml
source_type: terms_of_service
coverage_claims:
  - role: dpa
    coverage_type: contains
    evidence: "The same page includes a data processing addendum section."
  - role: ai_terms
    coverage_type: contains
    evidence: "The same page includes AI-specific terms."
```

Example for a trust center that links to a distinct public certification page:

```yaml
source_type: trust_center
coverage_claims:
  - role: certification_reference
    coverage_type: links_to
    evidence: "The trust center links to public certification information."
    target_url: https://vendor.example/trust/certifications
```

## 5. Add artifact records

An artifact record points to the assurance artifact represented by the source.

A source and artifact can have the same ID when they represent the same public page.

## 6. Leave hashes as TBD unless observation was run

It is acceptable to use:

```yaml
raw_sha256: sha256:TBD
normalized_text_sha256: sha256:TBD
```

Do not invent hashes.

## 7. Regenerate indexes

Run:

```bash
python -m tools.openva.validate build-indexes
python -m tools.openva.validate validate
pytest -q
```

## 8. Pull request checklist

Before opening a pull request, check:

- the source is public;
- the domain belongs to the vendor or a clearly official publishing domain;
- there are no duplicate source URLs;
- IDs match their file paths;
- summaries are factual and non-advisory;
- no raw vendor document was committed;
- generated indexes are updated.
