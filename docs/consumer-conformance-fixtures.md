# Consumer Conformance Fixtures

OpenVA fixture packs help downstream importers test pack handling without depending on the live catalog.

The fixtures live in:

```text
fixtures/packs/
```

Each fixture contains its own:

```text
openva-pack.json
indexes/vendors.json
indexes/sources.json
indexes/artifacts.json
indexes/observations.json
indexes/changes.json
indexes/summary.json
```

## Checker

Run the conformance checker against a fixture pack directory:

```bash
python -m tools.openva.conformance fixtures/packs/minimal-valid
```

The checker validates consumer-facing import safety:

- export profile ID;
- export schema version;
- transition aliases;
- required index keys;
- index path containment;
- index counts;
- summary counts;
- pack guarantees;
- source and artifact URL safety;
- non-`ok` observation hash behavior;
- raw-document storage flags;
- prohibited advisory wording.

## Fixtures

### `minimal-valid`

Expected result:

```text
pass
```

Purpose: smallest valid pack shape for importers.

### `valid-bot-protected-observation`

Expected result:

```text
pass
```

Purpose: confirms that `bot_protected` is a valid observation result when hashes remain `sha256:TBD` and raw storage remains false.

### `invalid-missing-guarantee`

Expected result:

```text
fail
```

Purpose: confirms consumers reject packs missing required OpenVA guarantees.

### `invalid-unsafe-url`

Expected result:

```text
fail
```

Purpose: confirms consumers reject unsafe source URLs such as localhost or private targets.

### `invalid-advisory-wording`

Expected result:

```text
fail
```

Purpose: confirms consumers reject pack metadata containing prohibited advisory wording.

## Boundary

These fixtures are not vendor records and are not catalog entries. They are importer conformance fixtures only.

They must not be used as evidence about any vendor.
