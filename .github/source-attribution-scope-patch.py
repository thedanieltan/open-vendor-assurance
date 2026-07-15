from pathlib import Path

path = Path("docs/operations/contracts/work-package-scope.yaml")
text = path.read_text(encoding="utf-8")
marker = "  WP-SOURCE-HEALTH-LABEL-RECONCILIATION-01:\n"
block = """  WP-SOURCE-PUBLISHER-ATTRIBUTION-01:
    description: Cross-domain source publisher attribution, product-applicability admission, public presentation, exports, catalog-quality audit, and bounded catalog backfill.
    allowed_paths:
      - .github/workflows/coverage-audit.yml
      - adapters/python/openva_csv_export/openva_csv_export/exporter.py
      - adapters/python/openva_sqlite_export/openva_sqlite_export/exporter.py
      - data/vendors/*/sources/*.yaml
      - dist/vendors/*.json
      - docs/source-publisher-attribution.md
      - indexes/sources.json
      - schemas/openva/source-reference.schema.json
      - site/build_core.py
      - site/src/app.js
      - site/src/styles.css
      - tests/test_source_attribution.py
      - tools/openva/catalog_guard.py
      - tools/openva/source_attribution.py

"""

if "WP-SOURCE-PUBLISHER-ATTRIBUTION-01:" not in text:
    if marker not in text:
        raise SystemExit("scope insertion marker not found")
    text = text.replace(marker, block + marker, 1)
    path.write_text(text, encoding="utf-8")
