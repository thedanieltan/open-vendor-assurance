# OpenVA JSONL Export

Pipeline-friendly JSONL export adapter for OpenVA public metadata packs.

## Install

```bash
python -m pip install adapters/python/openva_pack_reader
python -m pip install adapters/python/openva_jsonl_export
```

## Basic usage

```bash
python -m openva_jsonl_export --pack . --out ./openva-jsonl
```

Or from Python:

```python
from openva_jsonl_export import export_jsonl

paths = export_jsonl(".", "./openva-jsonl")
```

The adapter writes one compact JSON object per line with LF line endings and UTF-8 encoding. Lists and objects remain native JSON values.

## Boundary

JSONL records include `record_class`, `canonical`, and `advisory_boundary`. The export preserves OpenVA public metadata semantics and does not emit legal, compliance, procurement, security, KYC, AML, approval, suitability, or vendor-risk determinations.
