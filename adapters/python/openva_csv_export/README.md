# OpenVA CSV Export

Spreadsheet-friendly CSV export adapter for OpenVA public metadata packs.

## Install

```bash
python -m pip install adapters/python/openva_pack_reader
python -m pip install adapters/python/openva_csv_export
```

## Basic usage

```bash
python -m openva_csv_export --pack . --out ./openva-csv
```

Or from Python:

```python
from openva_csv_export import export_csvs

paths = export_csvs(".", "./openva-csv")
```

The adapter writes curated CSV files for vendors, sources, artifacts, observations, candidate sources, unavailable sources, and source coverage. List and object cells are compact JSON strings.

## Boundary

Every row includes adapter annotations such as `record_class`, `canonical`, and `advisory_boundary`. CSV exports preserve canonical, candidate, unavailable, observation, and coverage semantics; they do not turn OpenVA metadata into vendor approval, compliance, suitability, or risk claims.
