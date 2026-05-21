# OpenVA Pack Reader

Read-only Python reader for OpenVA public metadata packs.

## Install

```bash
python -m pip install adapters/python/openva_pack_reader
```

## Basic usage

```python
from openva_pack_reader import OpenVAPack

pack = OpenVAPack.load(".")
vendors = pack.vendors()
sources = pack.canonical_sources()
stripe = pack.vendor("stripe")
```

`OpenVAPack.load()` accepts a pack directory or a direct path to `openva-pack.json`. The reader validates pack guarantees, resolves advertised index paths, and annotates records with `record_class`, `canonical`, and `advisory_boundary`.

## Boundary

The pack reader is read-only. It exposes OpenVA public metadata references only and does not make legal, compliance, procurement, security, KYC, AML, approval, suitability, or vendor-risk decisions.
