"""Temporary acceptance smoke for the shipped human and agent user paths.

This branch is not intended for merge. It exercises current ``main`` through the
same static catalog and cached pack that public users consume.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path("adapters/python/openva_pack_reader").resolve()))
sys.path.insert(0, str(Path("adapters/python/openva_vendor_inventory_matcher").resolve()))
sys.path.insert(0, str(Path("services/openva_match_service").resolve()))

from openva_match_service.app import create_app  # noqa: E402
from openva_match_service.config import ServiceConfig  # noqa: E402


def test_human_browser_local_csv_resolves_known_and_unknown_vendor(tmp_path: Path) -> None:
    """Build the Pages artifact and execute its browser-local matcher primitives."""

    site_out = tmp_path / "site"
    subprocess.run(
        [sys.executable, "site/build.py", "--out", str(site_out)],
        check=True,
        text=True,
    )

    node_script = r"""
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const root = process.argv[1];
let appSource = fs.readFileSync(path.join(root, "app.js"), "utf8");
appSource = appSource.replace(/\ninit\(\);\s*$/, "\n");
const vendorSearch = JSON.parse(fs.readFileSync(path.join(root, "data/vendor-search.min.json"), "utf8"));
const stripeDetail = JSON.parse(fs.readFileSync(path.join(root, "data/vendors/stripe.json"), "utf8"));

const selectedFields = ["trust_security", "dpa", "subprocessors", "privacy_notice", "status_page"]
  .map((sourcePackField) => ({ dataset: { sourcePackField }, checked: true }));
const context = {
  console,
  Map,
  Set,
  Promise,
  JSON,
  String,
  Array,
  Object,
  Number,
  Date,
  Blob: function Blob() {},
  URL: { createObjectURL: () => "blob:smoke", revokeObjectURL: () => {} },
  document: {
    querySelectorAll: (selector) => selector.includes("data-source-pack-field") ? selectedFields : [],
    createElement: () => ({ click: () => {} }),
  },
  vendorSearch,
  stripeDetail,
};
vm.createContext(context);
vm.runInContext(appSource, context);
vm.runInContext(
  "catalogData = { meta: {}, vendors: vendorSearch.items, sourceTypes: [] }; vendorDetailsCache.set('stripe', stripeDetail);",
  context,
);

(async () => {
  const result = await vm.runInContext(`(async () => {
    const input = parseCsv('vendor_name,domain\\nStripe,stripe.com\\nUnknown Vendor,unknown.invalid\\n');
    const indexes = buildLocalMatchIndexes();
    const rows = await Promise.all(input.map((row, index) => matchInventoryRow(row, index, indexes)));
    return { input, rows, csv: resultPackCsv(input, rows) };
  })()`, context);
  process.stdout.write(JSON.stringify(result));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""

    completed = subprocess.run(
        ["node", "-e", node_script, str(site_out)],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    known, unknown = result["rows"]
    assert known["result_pack_version"] == "2.0.0"
    assert known["matched_vendor_name"] == "Stripe"
    assert known["official_domain"] == "stripe.com"
    assert known["dpa_url"].startswith("https://")
    assert unknown["matched_vendor_name"] is None
    assert unknown["official_domain"] is None
    assert "matched_vendor_name" in result["csv"]
    assert "Stripe" in result["csv"]


def test_agent_enrichment_returns_identity_and_source_references() -> None:
    """Exercise the zero-install agent HTTP contract with match and no-match rows."""

    app = create_app(
        ServiceConfig(
            pack_path=Path("."),
            api_key="smoke-key",
            public_read_enabled=True,
        )
    )
    payload = {
        "vendors": [
            {"row_id": "known", "vendor_name": "Stripe", "domain": "stripe.com"},
            {"row_id": "unknown", "vendor_name": "Definitely Not A Vendor 9000"},
        ],
        "source_types": ["dpa", "privacy_notice"],
    }

    with TestClient(app) as client:
        meta = client.get("/v1/catalog/meta")
        response = client.post("/v1/enrich", json=payload)

    assert meta.status_code == 200
    assert meta.json()["snapshot"]["vendor_count"] > 0
    assert meta.json()["snapshot"]["source_count"] > 0
    assert response.status_code == 200

    body = response.json()
    known, unknown = body["results"]
    assert [known["row_id"], unknown["row_id"]] == ["known", "unknown"]
    assert known["identity"]["match_status"] == "match"
    assert known["identity"]["matched_vendor_id"] == "stripe"
    assert known["source_references"]["dpa"]["status"] == "indexed"
    assert known["source_references"]["dpa"]["url"].startswith("https://")
    assert unknown["identity"]["match_status"] == "no_match"
    assert unknown["identity"]["no_match_reason"] == "no_indexed_openva_match"
    assert known["not_advice"] is True
    assert unknown["not_advice"] is True
    assert body["not_advice"] is True
