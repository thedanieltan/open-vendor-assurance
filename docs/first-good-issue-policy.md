# First Good Issue Policy

OpenVA welcomes new contributors, but public-good infrastructure needs narrow contribution boundaries.

This policy defines what can be labelled `good-first-issue`.

## Suitable good first issues

Good first issues should be low-risk, reviewable, and easy to reverse.

Suitable examples:

- fix typos in documentation;
- clarify non-advisory wording in docs;
- improve examples without changing schemas;
- add tests for existing behavior;
- improve fixture documentation;
- add one clearly public source reference after maintainer approval;
- correct a broken public URL when the replacement is vendor-controlled and public;
- improve comments or error messages without changing behavior.

## Not suitable for good first issues

Do not label these as `good-first-issue`:

- schema changes;
- pack contract changes;
- workflow permission changes;
- observation fetch behavior;
- URL safety logic;
- validator behavior;
- release/versioning policy;
- security policy;
- license changes;
- governance changes;
- non-English legal-source interpretation;
- KYC, AML, sanctions, or regulated-finance metadata;
- large catalog batches;
- vendor-submitted corrections involving disputed metadata;
- any issue involving gated/private/customer-specific materials.

## Maintainer checklist

Before applying `good-first-issue`, confirm:

- the expected outcome is clear;
- the contributor does not need private context;
- the issue does not require legal, compliance, procurement, or security judgment;
- the change can be reviewed from public sources;
- the change is unlikely to affect downstream import compatibility;
- the change is not a project-boundary decision.

## Suggested issue wording

Good first issues should include:

- the file or area to change;
- the expected output;
- validation commands;
- links to relevant policy docs;
- a reminder to avoid advisory language.

Example:

```md
Update `docs/consumer-conformance-fixtures.md` to clarify that invalid fixture packs are intentionally invalid and should be tested through `pytest`, not imported as valid packs.

Run:

```bash
pytest -q
```

Do not change fixture schema, pack contract, or live catalog data.
```
