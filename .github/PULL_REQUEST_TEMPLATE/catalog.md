## Catalog batch summary

List the vendors added or updated.

```text
- vendor-id-1
- vendor-id-2
- vendor-id-3
```

## Source URLs

List the public source URLs used.

```text
- https://vendor.example/legal/dpa
- https://vendor.example/trust/subprocessors
```

## Catalog-agent boundary

- [ ] This PR changes only allowed catalog-lane files.
- [ ] This PR adds or updates no more than five vendors.
- [ ] This PR does not modify schemas, tools, tests, workflows, policy files, README, CONTRIBUTING, SECURITY, LICENSE, or CODEOWNERS.
- [ ] This PR does not change observation behavior, pack contract, validator behavior, or release semantics.

## Public-source check

- [ ] Every source is public.
- [ ] Every source is vendor-controlled, regulator-controlled, or standards-body-controlled.
- [ ] No source requires login, credentials, NDA, customer status, sales approval, support ticket access, private portal access, form submission, or anti-bot bypass.
- [ ] Any rejected or skipped sources are listed below.

## Metadata-only check

- [ ] No raw PDF, raw HTML, screenshot, extracted full text, portal export, SOC report, ISO certificate, bespoke agreement, or customer-specific material is committed.
- [ ] Hashes remain `sha256:TBD` unless produced by approved OpenVA observation tooling.

## Non-advisory check

- [ ] No legal advice.
- [ ] No compliance advice.
- [ ] No procurement advice.
- [ ] No risk score.
- [ ] No vendor recommendation.
- [ ] No claim that a vendor is compliant, safe, approved, adequate, suitable, recommended, or low/high risk.

## Language check

- [ ] Source language is recorded accurately.
- [ ] Native-language title or context is preserved where practical.
- [ ] English summaries, if present, are convenience metadata only.
- [ ] Maintainer review is requested for any source language the agent could not confidently interpret.

## Generated files

- [ ] `python -m tools.openva.validate build-indexes` was run.
- [ ] `indexes/**` was updated if catalog records changed.
- [ ] `openva-pack.json` was updated if catalog records changed.

## Validation

Commands run:

```bash
python -m tools.openva.validate build-indexes
python -m tools.openva.validate validate
pytest -q
```

## Rejected or skipped sources

List any sources considered but rejected, and explain why.

```text
- URL: reason
```

## Maintainer review triggers

Check any that apply:

- [ ] Source is hard to classify.
- [ ] Source language requires review.
- [ ] Vendor has unusual public-source structure.
- [ ] Existing metadata may conflict with new source.
- [ ] A new schema field or artifact type may be needed.
- [ ] Other boundary concern: explain below.
