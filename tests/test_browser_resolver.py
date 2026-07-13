from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


def site_build_module():
    spec = importlib.util.spec_from_file_location("openva_site_build_browser_test", SITE / "build.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compiled_catalog_publishes_only_bounded_registration_match_keys():
    compiled = site_build_module().build_compiled_catalog()
    vendors = {row["vendor_id"]: row for row in compiled["vendor_summaries"]}

    assert vendors["adobe"]["registration_keys"] == [
        {
            "jurisdiction": "US",
            "legal_name": "Adobe Inc.",
            "registration_number": "0000796343",
        }
    ]
    assert vendors["atlassian"]["registration_keys"]

    allowed = {"registration_number", "jurisdiction", "legal_name"}
    for vendor in vendors.values():
        for key in vendor["registration_keys"]:
            assert set(key) == allowed
            assert "_openva_path" not in key
            assert "verification_source_ids" not in key
            assert "notes" not in key


def test_static_site_vendor_index_contains_registration_match_keys(tmp_path: Path):
    module = site_build_module()
    output = tmp_path / "site-dist"
    module.build_site(output)

    payload = json.loads((output / "data" / "vendor-search.min.json").read_text(encoding="utf-8"))
    vendors = {row["vendor_id"]: row for row in payload["items"]}

    assert payload["meta"]["vendor_count"] == len(vendors)
    assert vendors["adobe"]["registration_keys"][0]["registration_number"] == "0000796343"


def test_browser_resolver_source_carries_explicit_fail_closed_contract():
    source = (SITE / "src" / "ui-fixes.js").read_text(encoding="utf-8")

    required_tokens = {
        'company: "vendor_name"',
        'website: "domain"',
        'uen: "registration_number"',
        'method: "domain_subdomain"',
        'method: "registration_number_exact"',
        'status: "ambiguous"',
        '"openva_match_status"',
        '"openva_match_note"',
        "No supported identity column was found",
        "No inventory data was uploaded",
    }
    for token in required_tokens:
        assert token in source


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_browser_resolver_javascript_executes_matching_contract(tmp_path: Path):
    source = (SITE / "src" / "ui-fixes.js").read_text(encoding="utf-8")
    marker = "\n})();\n"
    assert source.endswith(marker)
    exports = """
  globalThis.__openvaResolverTest = {
    parseInventoryCsv,
    normalizeDomainValue,
    buildResolverIndexes,
    matchingDecision,
  };
"""
    instrumented = source[: -len(marker)] + exports + marker

    harness = f"""
const vm = require("node:vm");
const assert = require("node:assert/strict");

const context = {{
  console,
  URL,
  setTimeout: () => 0,
  clearTimeout: () => {{}},
  localStorage: {{ getItem: () => null, setItem: () => {{}} }},
  document: {{
    documentElement: {{ dataset: {{}}, removeAttribute: () => {{}} }},
    querySelector: () => null,
    querySelectorAll: () => [],
    getElementById: () => null,
    addEventListener: () => {{}},
    head: {{ appendChild: () => {{}} }},
    createElement: () => ({{
      addEventListener: () => {{}},
      append: () => {{}},
      appendChild: () => {{}},
      classList: {{ add: () => {{}} }},
      dataset: {{}},
      setAttribute: () => {{}},
    }}),
  }},
  catalogData: {{
    vendors: [
      {{
        vendor_id: "adobe",
        display_name: "Adobe",
        legal_name: "Adobe Inc.",
        official_domains: ["adobe.com"],
        registration_keys: [{{
          registration_number: "0000796343",
          jurisdiction: "US",
          legal_name: "Adobe Inc.",
        }}],
      }},
      {{
        vendor_id: "atlassian",
        display_name: "Atlassian",
        legal_name: "Atlassian Pty Ltd",
        official_domains: ["atlassian.com"],
        registration_keys: [{{
          registration_number: "53102443916",
          jurisdiction: "AU",
          legal_name: "Atlassian Pty Ltd",
        }}],
      }},
    ],
  }},
}};
context.window = context;
context.globalThis = context;
vm.runInNewContext({json.dumps(instrumented)}, context, {{ filename: "ui-fixes.js" }});

const resolver = context.__openvaResolverTest;
const parsed = resolver.parseInventoryCsv(
  "Company;Website;UEN;Country\\nAdobe;https://security.adobe.com/path;0000796343;US\\n"
);
assert.equal(parsed.length, 1);
assert.equal(parsed[0].vendor_name, "Adobe");
assert.equal(parsed[0].domain, "https://security.adobe.com/path");
assert.equal(parsed[0].registration_number, "0000796343");
assert.equal(parsed[0].jurisdiction, "US");

const indexes = resolver.buildResolverIndexes();
let decision = resolver.matchingDecision({{ domain: "https://security.adobe.com/path" }}, indexes);
assert.equal(decision.status, "matched");
assert.equal(decision.vendor.vendor_id, "adobe");
assert.equal(decision.method, "domain_subdomain");

decision = resolver.matchingDecision({{ business_entity_name: "Adobe Incorporated" }}, indexes);
assert.equal(decision.status, "no_match");

decision = resolver.matchingDecision({{ business_entity_name: "Adobe Inc." }}, indexes);
assert.equal(decision.status, "matched");
assert.equal(decision.vendor.vendor_id, "adobe");
assert.equal(decision.method, "name_exact");

decision = resolver.matchingDecision(
  {{ registration_number: "53 102 443 916", jurisdiction: "AU" }}, indexes
);
assert.equal(decision.status, "matched");
assert.equal(decision.vendor.vendor_id, "atlassian");
assert.equal(decision.method, "registration_number_exact");

decision = resolver.matchingDecision(
  {{ domain: "adobe.com", registration_number: "53102443916", jurisdiction: "AU" }}, indexes
);
assert.equal(decision.status, "ambiguous");
assert.equal(decision.vendor, null);
"""
    script = tmp_path / "browser-resolver-contract.cjs"
    script.write_text(harness, encoding="utf-8")

    completed = subprocess.run(
        [shutil.which("node") or "node", str(script)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
