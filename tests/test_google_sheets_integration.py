"""Temporary browser-local human-user smoke; this branch is never merged."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_generated_browser_app_projects_neutral_no_match(tmp_path: Path) -> None:
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
};
vm.createContext(context);
vm.runInContext(appSource, context);
const result = vm.runInContext(
  "browserResultPackRow({ vendor_name: 'Unknown Vendor', domain: 'unknown.invalid' }, 0, null)",
  context,
);
process.stdout.write(JSON.stringify(result));
"""

    completed = subprocess.run(
        ["node", "-e", node_script, str(site_out)],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["result_pack_version"] == "2.0.0"
    assert result["input_vendor_name"] == "Unknown Vendor"
    assert result["matched_vendor_name"] is None
    assert result["official_domain"] is None
    assert result["dpa_url"] is None
