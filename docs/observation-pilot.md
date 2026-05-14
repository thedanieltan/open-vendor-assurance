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

The source appears public, but automation was blocked or challenged by anti-bot behavior, access controls, or bot-protection status codes.

OpenVA must not bypass the protection. No hashes are produced.

### `fetch_failed`

The request failed for reasons other than recognised bot protection or quarantining.

### `quarantined`

The URL or redirect target failed URL-safety checks.

## Boundary

The observation pilot must not:

- log in;
- submit forms;
- solve CAPTCHAs;
- rotate proxies;
- bypass anti-bot controls;
- store raw documents;
- store screenshots;
- generate legal, compliance, procurement, security, KYC, AML, or risk conclusions.
