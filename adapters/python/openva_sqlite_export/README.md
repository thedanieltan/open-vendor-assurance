# OpenVA SQLite Export

Local SQLite export adapter for OpenVA public metadata packs.

## Install

```bash
python -m pip install adapters/python/openva_pack_reader
python -m pip install adapters/python/openva_sqlite_export
```

## Basic usage

```bash
python -m openva_sqlite_export --pack . --out ./openva.sqlite
```

Or from Python:

```python
from openva_sqlite_export import export_sqlite

db_path = export_sqlite(".", "./openva.sqlite")
```

If the output database already exists, it is replaced. This adapter is an export generator; it does not append to or migrate existing SQLite files.

## Boundary

SQLite tables preserve OpenVA record classes and non-advisory annotations. The database is for local analysis of public metadata references, not vendor approval, compliance, suitability, or risk decisions.
