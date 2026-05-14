# Release Checklist

Use this checklist before tagging an OpenVA release.

## Preflight

- [ ] Confirm this is a catalog-only release, substrate release, or mixed release.
- [ ] Confirm whether any schema, pack, profile, or importer compatibility changes exist.
- [ ] Confirm release notes include known limitations and non-advisory boundaries.

## Required commands

Run the full release smoke test:

```bash
python -m tools.openva.release_smoke
```

The smoke test covers the core release checklist. Maintainers may also run the underlying commands individually:

```bash
python -m tools.openva.validate build-indexes
python -m tools.openva.validate validate
pytest -q
python -m tools.openva.conformance fixtures/packs/minimal-valid
python -m tools.openva.conformance fixtures/packs/valid-bot-protected-observation
```

## Generated files

- [ ] `openva-pack.json` is committed and current.
- [ ] `indexes/*.json` are committed and current.
- [ ] No generated diff remains after `build-indexes`.

## Compatibility

- [ ] `profileId` is correct.
- [ ] `schemaVersion` is correct.
- [ ] `packId` is correct.
- [ ] `schema_version` is correct.
- [ ] Compatibility-impacting changes are explicitly called out.
- [ ] Breaking changes are explicitly called out.
- [ ] Consumer pinning guidance is included.

## Scope and safety

- [ ] No raw vendor documents are committed by default.
- [ ] No screenshots are committed by default.
- [ ] No portal exports are committed.
- [ ] No private SOC reports are committed.
- [ ] No private ISO certificates are committed.
- [ ] No customer-specific or bespoke agreements are committed.
- [ ] No gated materials are committed.
- [ ] No advisory wording is introduced.

## Release notes

Release notes should include:

- [ ] Summary.
- [ ] Compatibility.
- [ ] Pack profile.
- [ ] Pack schema.
- [ ] Catalog changes, if any.
- [ ] Observation changes, if any.
- [ ] Tooling changes, if any.
- [ ] Governance/docs changes, if any.
- [ ] Conformance fixture changes, if any.
- [ ] Known limitations.
- [ ] Upgrade notes.

## Tagging

Suggested tag format:

```text
v0.1.0
v0.1.1
v0.2.0
```

Do not tag until CI is green and generated files are current.
