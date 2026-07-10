"""Temporary browser-local human-user smoke; this branch is never merged."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_generated_browser_app_builds_vendor_match_indexes(tmp_path: Path) -> None:
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
  document: { querySelectorAll: () => [], createElement: () => ({ click: () => {} }) },
  vendorSearch,
};
vm.createContext(context);
vm.runInContext(appSource, context);
const result = vm.runInContext(`(() => {
  catalogData = { meta: {}, vendors: vendorSearch.items, sourceTypes: [] };
  const indexes = buildLocalMatchIndexes();
  const byDomain = indexes.domainIndex.get('adp.com');
  const byName = indexes.nameIndex.get('adp');
  return {
    hasDomain: indexes.domainIndex.has('adp.com'),
    hasName: indexes.nameIndex.has('adp'),
    domainVendorId: byDomain && byDomain.vendor_id,
    nameVendorId: byName && byName.vendor_id,
  };
})()`, context);
process.stdout.write(JSON.stringify(result));
"""

    completed = subprocess.run(
        ["node", "-e", node_script, str(site_out)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == {
        "hasDomain": True,
        "hasName": True,
        "domainVendorId": "adp",
        "nameVendorId": "adp",
    }
