# Contribution Promotion Materializer

The contribution promotion materializer is the next gated step after the contribution promotion queue.

The queue classifies contributor-submitted source candidates. The materializer can then turn `machine_validated_promotions` into deterministic canonical source YAML files.

## Boundary

The materializer writes canonical source files only when explicitly invoked with `--apply`.

It does not:

- fetch the network;
- classify contributor input itself;
- open pull requests;
- merge pull requests;
- approve vendors;
- score vendor risk;
- make legal, compliance, procurement, security, KYC, AML, sanctions, or certification-validity conclusions.

## Dry run

By default, the materializer reports what it would write without changing the repository.

```bash
python -m tools.openva.contribution_promotion_materializer materialize \
  --queue .openva-promotion-queue/queue.json \
  --out .openva-promotion-queue/materialize-report.json
```

## Apply

To create source YAML files:

```bash
python -m tools.openva.contribution_promotion_materializer materialize \
  --queue .openva-promotion-queue/queue.json \
  --out .openva-promotion-queue/materialize-report.json \
  --apply
```

After applying, rebuild generated outputs and validate:

```bash
python -m tools.openva.validate validate
python -m tools.openva.validate build-indexes
git diff --exit-code openva-pack.json indexes/
python -m pytest -q
```

## Conflict behavior

If a target source file already exists with the same URL and source type, it is skipped as existing.

If a target source file exists with a different URL or source type, the materializer reports a conflict and does not overwrite it by default.

Overwrites require an explicit `--overwrite` flag and should remain human-reviewed.

## Required source posture

Only machine-validated source records can be materialized:

```text
catalog_tier: machine_validated
review_state: auto_validated
advisory_boundary: non_advisory
not_advice: true
```

The result is a canonical public source reference, not an assurance conclusion.
