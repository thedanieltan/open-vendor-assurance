# Batch Materialization Workflow

OpenVA distinguishes between planned batch manifests and materialized catalog records.

A vendor in a batch manifest is not counted as catalog coverage until it has committed records under:

```text
data/vendors/{vendor_id}/vendor.yaml
data/vendors/{vendor_id}/sources/*.yaml
data/vendors/{vendor_id}/artifacts/*.yaml
```

and generated indexes have been rebuilt.

## Purpose

The materialization workflow converts already-merged catalog-batch manifests into canonical vendor/source/artifact records in bounded PRs.

This closes the gap between:

```text
planned vendors in catalog-batches/*.yaml
```

and:

```text
materialized vendors in data/vendors/**
```

## Commands

Plan pending materialization for a lane:

```bash
python -m tools.openva.materialize_batches plan --lane infra-data-ai-devtools --output materialization-plan.json
```

Run materialization for a lane:

```bash
python -m tools.openva.materialize_batches run --lane infra-data-ai-devtools --output materialization-report.json
```

The `run` command:

- skips manifests whose vendors are already fully materialized;
- runs the existing catalog-batch generator for pending manifests;
- rebuilds indexes and `openva-pack.json` after generation;
- does not fetch live vendor content;
- does not mirror raw documents;
- does not use gated/private materials.

## Workflow

Manual workflow:

```text
materialize batches PR
```

The workflow:

- requires manual dispatch;
- requires `branch_name` to start with `agent-`;
- requires `pr_title` to start with `Catalog:`;
- creates a pull request only;
- does not merge PRs;
- does not write directly to `main`;
- does not fetch live vendor content.

## Lanes

Lanes are configured in:

```text
config/materialization-lanes.yaml
```

Supported lanes:

```text
infra-data-ai-devtools
payments-kyc-fintech
hr-health-education-logistics
collaboration-commerce-grc
regional-apac-china
```

## Review posture

Every materialization PR should be reviewed for:

```text
public-source-only metadata
no raw document mirroring
no gated or private materials
no duplicate vendors
no semantic duplicate vendors
generated index consistency
coverage audit impact
```

## Non-advisory boundary

Materializing a vendor record does not mean the vendor is approved, safe, compliant, low risk, suitable, certified, recommended, or adequate for any workload, organization, jurisdiction, procurement decision, audit, or legal obligation.
