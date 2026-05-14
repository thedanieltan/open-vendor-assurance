# Observation Pilot

P17 introduced a narrow observation pilot for selected public sources. P18 hardens the pilot output and write behavior before broader automation.

The goal is to validate observation behavior before running automated observation across the catalog or using observations in export-pack trust signals.

## Pilot scope

The pilot source list lives in:

```text
config/observation-pilot.yaml
```

The pilot must stay small and controlled until observation behavior is proven against real public sources.

## Run dry-run pilot

```bash
python -m tools.openva.observe observe-pilot --dry-run
```

Dry-run output defaults to a compact summary:

```text
OpenVA observation summary
mode: dry-run
sources: 5
bot_protected: 1
ok: 4

Results by source:
- example-source: ok (http=200, final_url=https://example.com)
```

Dry-run does not write files.

To inspect raw observation YAML after the compact summary:

```bash
python -m tools.openva.observe observe-pilot --dry-run --emit-yaml
```

## Write pilot observations

```bash
python -m tools.openva.observe observe-pilot
python -m tools.openva.validate build-indexes
python -m tools.openva.validate validate
pytest -q
```

Only maintainers should write pilot observations until the behavior is proven.

Ambiguous results are skipped by default during write runs:

```text
bot_protected
size_limited
fetch_failed
quarantined
```

A maintainer can intentionally write ambiguous results with:

```bash
python -m tools.openva.observe observe-pilot --allow-ambiguous-write
```

Use that override only when the result itself is meaningful public history.

## Result taxonomy

See:

```text
docs/observation-result-taxonomy.md
```

## Boundary

The observation pilot must not:

- use credentials or private access;
- submit forms;
- perform restricted-access workarounds;
- bypass anti-bot, CAPTCHA, login, portal, or access-control systems;
- collect gated materials;
- store raw documents;
- store screenshots;
- hash partial oversized responses;
- generate legal, compliance, procurement, security, KYC, AML, or risk conclusions.
