"""Temporary browser-local human-user smoke; this branch is never merged."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_human_can_resolve_csv_and_export_results_in_browser(tmp_path: Path) -> None:
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
const knownVendor = vendorSearch.items.find((vendor) => vendor.vendor_id === "adp");
if (!knownVendor) throw new Error("ADP missing from generated browser index");
const knownDetail = JSON.parse(fs.readFileSync(path.join(root, knownVendor.detail_path), "utf8"));

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
  knownVendor,
  knownDetail,
};
vm.createContext(context);
vm.runInContext(appSource, context);
vm.runInContext(
  "catalogData = { meta: {}, vendors: vendorSearch.items, sourceTypes: [] }; vendorDetailsCache.set(knownVendor.vendor_id, knownDetail);",
  context,
);

(async () => {
  const result = await vm.runInContext(`(async () => {
    const input = parseCsv('vendor_name,domain\\nADP,adp.com\\nUnknown Vendor,unknown.invalid\\n');
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
    assert known["matched_vendor_name"] == "ADP"
    assert known["official_domain"] == "adp.com"
    assert known["dpa_url"].startswith("https://")
    assert unknown["matched_vendor_name"] is None
    assert unknown["official_domain"] is None
    assert "matched_vendor_name" in result["csv"]
    assert "dpa_url" in result["csv"]
    assert "ADP" in result["csv"]
