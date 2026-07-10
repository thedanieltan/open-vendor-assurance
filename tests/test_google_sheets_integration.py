"""Temporary browser-local human-user smoke; this branch is never merged."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_generated_browser_app_parses_csv(tmp_path: Path) -> None:
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
  document: {
    querySelectorAll: () => [],
    createElement: () => ({ click: () => {} }),
  },
};
vm.createContext(context);
vm.runInContext(appSource, context);
const rows = vm.runInContext(
  "parseCsv('vendor_name,domain\\nADP,adp.com\\nUnknown Vendor,unknown.invalid\\n')",
  context,
);
process.stdout.write(JSON.stringify(rows));
"""

    completed = subprocess.run(
        ["node", "-e", node_script, str(site_out)],
        check=True,
        capture_output=True,
        text=True,
    )
    rows = json.loads(completed.stdout)
    assert rows == [
        {"vendor_name": "ADP", "domain": "adp.com"},
        {"vendor_name": "Unknown Vendor", "domain": "unknown.invalid"},
    ]
