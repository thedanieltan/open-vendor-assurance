"""Temporary browser-local human-user smoke; this branch is never merged."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_generated_browser_app_matches_known_and_unknown_vendor(tmp_path: Path) -> None:
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
const knownDetail = JSON.parse(fs.readFileSync(path.join(root, "data/vendors/adp.json"), "utf8"));
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
    querySelectorAll: () => [],
    createElement: () => ({ click: () => {} }),
  },
  vendorSearch,
  knownDetail,
};
vm.createContext(context);
vm.runInContext(appSource, context);
vm.runInContext(
  "catalogData = { meta: {}, vendors: vendorSearch.items, sourceTypes: [] }; vendorDetailsCache.set('adp', knownDetail);",
  context,
);

(async () => {
  const rows = await vm.runInContext(`(async () => {
    const input = parseCsv('vendor_name,domain\\nADP,adp.com\\nUnknown Vendor,unknown.invalid\\n');
    const indexes = buildLocalMatchIndexes();
    return Promise.all(input.map((row, index) => matchInventoryRow(row, index, indexes)));
  })()`, context);
  process.stdout.write(JSON.stringify(rows));
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
    known, unknown = json.loads(completed.stdout)
    assert known["result_pack_version"] == "2.0.0"
    assert known["matched_vendor_name"] == "ADP"
    assert known["official_domain"] == "adp.com"
    assert unknown["matched_vendor_name"] is None
    assert unknown["official_domain"] is None
