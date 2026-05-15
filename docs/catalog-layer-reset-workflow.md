# Catalog Layer Reset Workflow

The catalog-layer reset workflow creates a pull request that removes and rebuilds the shallow generated catalog layer before a breadth-depth reseed.

This workflow exists because OpenVA's first catalog expansion produced too many one-artifact vendor records and too much separation between planned batch manifests and materialized canonical records.

## Workflow

```text
catalog reset PR
```

The workflow is manual-only and requires explicit confirmation:

```text
RESET-CATALOG-LAYER
```

It also requires:

```text
branch_name starts with reset-
pr_title starts with P:
```

## Reset scope

The reset targets the catalog layer:

```text
data/vendors/
catalog-batches/ stale or unmaterialized manifests
indexes/
openva-pack.json
```

The workflow runs `tools.openva.reset_catalog`, which removes the catalog layer and rebuilds generated indexes/pack state.

## Preserved substrate

The reset must preserve:

```text
schemas/
policy/
config/category-taxonomy.yaml
tools/
tests/
docs/
.github/workflows/
README.md
CONTRIBUTING.md
SECURITY.md
LICENSE
```

## Safety posture

- Manual dispatch only.
- Explicit confirmation required.
- Opens a pull request only.
- Does not merge automatically.
- Performs no live vendor fetches.
- Mirrors no raw documents.
- Uses no gated, private, NDA, portal-only, or customer-specific materials.
- Produces no legal, compliance, procurement, audit, security, or vendor-risk advice.

## After reset

After the reset PR is merged, reseed work must follow the same-PR rule:

```text
canonical records in the same PR
generated indexes in the same PR
validation in the same PR
```

Catalog PRs should include, when affected:

```text
data/vendors/{vendor_id}/vendor.yaml
data/vendors/{vendor_id}/sources/*.yaml
data/vendors/{vendor_id}/artifacts/*.yaml
indexes/*.json
openva-pack.json
```

## Reseed priority

Start with tier-1 vendors and useful public assurance artifacts:

```text
dpa
subprocessors_list
privacy_notice
security_page
trust_center
compliance_certifications_page
```

Where public artifacts are unavailable, record a coverage gap rather than inventing a substitute.
