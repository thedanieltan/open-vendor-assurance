# Observation Pilot

P17 introduces a narrow observation pilot for selected public sources.

The goal is to validate observation behavior before running broader automated observation across the catalog.

## Pilot scope

The pilot source list lives in:

```text
config/observation-pilot.yaml
```

The initial pilot focuses on a small set of cloud-provider public sources that already exist in OpenVA.

## Run dry-run pilot

```bash
python -m tools.openva.observe observe-pilot --dry-run
```

Dry-run output prints observation records to stdout and does not write files.

## Write pilot observations

```bash
python -m tools.openva.observe observe-pilot
python -m tools.openva.validate build-indexes
python -m tools.openva.validate validate
pytest -q
```

Only maintainers should write pilot observations until the behavior is proven.

## Result meanings

### `ok`

The public source was fetched without storing raw content. Hashes were computed from the fetched response.

### `bot_protected`

The source appears public to normal users, but OpenVA's transparent observer could not fetch it because the site required additional human or controlled-access interaction.

OpenVA respects that boundary. No hashes are produced.

### `size_limited`

The public source response exceeded OpenVA's observation byte limit.

OpenVA does not store or hash partial oversized responses in the pilot. No hashes are produced.

### `fetch_failed`

The request failed for reasons other than recognised access-boundary, size-limit, or quarantine outcomes.

### `quarantined`

The URL or redirect target failed URL-safety checks.

## Boundary

The observation pilot must not:

- use credentials or private access;
- submit forms;
- perform restricted-access workarounds;
- collect gated materials;
- store raw documents;
- store screenshots;
- hash partial oversized responses;
- generate legal, compliance, procurement, security, KYC, AML, or risk conclusions.
