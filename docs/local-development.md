# Local Development

OpenVA should be easy to validate from a fresh checkout.

## Recommended setup

```bash
python -m pip install -e ".[dev]"
```

Then run:

```bash
python -m tools.openva.validate build-indexes
python -m tools.openva.validate validate
pytest -q
```

## Fresh checkout behavior

`pytest -q` is configured to include the repository root on `PYTHONPATH`, so tests can import `tools.openva.*` when run from the repo root.

If tests are run from another directory, install the package in editable mode first.

## Generated files

When records change, regenerate indexes before committing:

```bash
python -m tools.openva.validate build-indexes
python -m tools.openva.validate validate
```

Commit changes to:

```text
indexes/
openva-pack.json
```
