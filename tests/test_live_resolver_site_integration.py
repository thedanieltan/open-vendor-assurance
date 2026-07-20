"""Deterministic coverage for the browser CSV resolver's opt-in live-discovery path.

Exercises site/src/app.js's live-resolver integration (matchInventoryRow, the
domain-confirmation / not-checked / live-outcome row builders, and the bounded,
deduplicated resolveLivePending orchestration) inside a Node vm sandbox, plus static
checks on the shipped markup (single central endpoint, opt-in default, disclosure text,
no banned terminology).
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE_SRC = ROOT / "site" / "src"

BANNED_TERMS = ("canonical", "noncanonical", "non-canonical")


def _run_node(script: str, tmp_path: Path, name: str = "live-resolver-contract.cjs") -> None:
    path = tmp_path / name
    path.write_text(script, encoding="utf-8")
    completed = subprocess.run(
        [shutil.which("node") or "node", str(path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_live_resolver_endpoint_is_declared_exactly_once():
    app_js = (SITE_SRC / "app.js").read_text(encoding="utf-8")
    occurrences = app_js.count("openva-live-resolver.danieltanyl91.workers.dev")
    assert occurrences == 1, "the deployed Worker URL must be declared in exactly one place"
    assert "const LIVE_RESOLVER_CONFIG" in app_js
    for other_src in SITE_SRC.glob("*.js"):
        if other_src.name == "app.js":
            continue
        assert "openva-live-resolver.danieltanyl91.workers.dev" not in other_src.read_text(encoding="utf-8")


def test_opt_in_toggle_defaults_off_with_disclosure():
    index_html = (SITE_SRC / "index.html").read_text(encoding="utf-8")
    match = re.search(
        r'<input type="checkbox" id="enable-live-resolution"[^>]*>',
        index_html,
    )
    assert match, "opt-in checkbox is missing"
    assert "checked" not in match.group(0), "live resolution must default to off"
    assert (
        "Only unmatched vendor names, domains, and requested public-source types are sent. "
        "Your CSV and other inventory fields remain in your browser."
    ) in index_html


def test_no_canonical_wording_introduced_in_live_resolver_surface():
    index_html = (SITE_SRC / "index.html").read_text(encoding="utf-8")
    app_js = (SITE_SRC / "app.js").read_text(encoding="utf-8")
    toggle_start = index_html.index('id="enable-live-resolution"')
    toggle_region = index_html[max(0, toggle_start - 400) : toggle_start + 400]
    for term in BANNED_TERMS:
        assert term not in toggle_region.lower()
    # Every openva_resolution_message literal introduced for the live-resolver integration.
    for message in re.findall(r'openva_resolution_message:\s*\n?\s*"([^"]+)"', app_js):
        for term in BANNED_TERMS:
            assert term not in message.lower()


def test_required_output_fields_are_present_in_row_builders():
    app_js = (SITE_SRC / "app.js").read_text(encoding="utf-8")
    for field in [
        "openva_resolution_status",
        "openva_result_origin",
        "openva_live_checked",
        "openva_checked_at",
        "openva_catalog_publication_status",
        "openva_resolution_message",
    ]:
        assert app_js.count(field) >= 2, f"{field} should be set by the row builders"


def _instrumented_source() -> str:
    source = (SITE_SRC / "app.js").read_text(encoding="utf-8")
    export_block = """
globalThis.__openvaLiveResolverTest = {
  matchInventoryRow,
  buildLocalMatchIndexes,
  buildDomainConfirmationFields,
  buildNotCheckedFields,
  applyLiveOutcomeToRow,
  resolveLivePending,
  selectedLiveSourceTypes,
  runWithConcurrency,
  setCatalogData: (data) => { catalogData = data; },
};
"""
    return source + "\n" + export_block


def test_catalog_match_skips_the_live_worker(tmp_path: Path):
    scenario = r'''
context.__fetchHandler = () => { throw new Error("must not call the live resolver for a catalog match"); };
context.__vendorDetails = {
  "data/vendors/adobe.json": { vendor: { vendor_id: "adobe", display_name: "Adobe" }, source_records: [] },
};
api.setCatalogData({
  vendors: [
    {
      vendor_id: "adobe", display_name: "Adobe", legal_name: "Adobe Inc.",
      official_domains: ["adobe.com"], detail_path: "data/vendors/adobe.json",
    },
  ],
});
(async () => {
  const indexes = api.buildLocalMatchIndexes();
  const row = await api.matchInventoryRow({ vendor_name: "Adobe", domain: "adobe.com" }, 0, indexes);
  assert.equal(row.matched_vendor_name, "Adobe");
  assert.equal(row.openva_resolution_status, "catalog_match");
  assert.equal(row.openva_result_origin, "published_catalog");
  assert.equal(row.openva_live_checked, false);
  assert.equal(row.openva_catalog_publication_status, "published_catalog_record");
})().catch((error) => { console.error(error); process.exit(1); });
'''
    node_script = (
        _preamble()
        + f"vm.runInNewContext({json.dumps(_instrumented_source())}, context, {{ filename: 'app.js' }});\n"
        + "const api = context.__openvaLiveResolverTest;\n"
        + scenario
    )
    _run_node(node_script, tmp_path)


def _preamble() -> str:
    return r'''
const vm = require("node:vm");
const assert = require("node:assert/strict");

const elementStub = () => ({
  addEventListener: () => {},
  dataset: {},
  classList: { add: () => {}, remove: () => {}, contains: () => false },
  style: {},
  set textContent(_v) {},
  set innerHTML(_v) {},
  value: "",
  checked: false,
  files: [],
});

const context = {
  console,
  URL,
  AbortController,
  setTimeout,
  clearTimeout,
  addEventListener: () => {},
  location: { hash: "", origin: "https://thedanieltan.github.io", pathname: "/" },
  document: {
    documentElement: { dataset: {}, removeAttribute: () => {} },
    querySelector: () => null,
    querySelectorAll: () => [],
    getElementById: () => elementStub(),
    addEventListener: () => {},
    head: { appendChild: () => {} },
    createElement: () => elementStub(),
  },
  fetch: (url, options) => {
    if (typeof url === "string" && url.startsWith("data/")) {
      if (context.__vendorDetails && context.__vendorDetails[url]) {
        return Promise.resolve({ ok: true, json: async () => context.__vendorDetails[url] });
      }
      return new Promise(() => {}); // init()'s own bootstrap fetches never resolve; harmless.
    }
    return context.__fetchHandler(url, options);
  },
};
context.window = context;
context.globalThis = context;
'''


def test_unmatched_with_domain_calls_worker_with_minimal_body(tmp_path: Path):
    scenario = r'''
let calls = [];
context.__fetchHandler = async (url, options) => {
  calls.push({ url, body: JSON.parse(options.body) });
  return {
    ok: true,
    json: async () => ({
      vendor: { official_domain: "example.com" },
      sources: [{ source_type: "privacy_notice", status: "not_found", source_url: null }],
    }),
  };
};
api.setCatalogData({ vendors: [] });
(async () => {
  const indexes = api.buildLocalMatchIndexes();
  const row = await api.matchInventoryRow({ vendor_name: "Example Co", domain: "example.com" }, 0, indexes);
  assert.equal(row.matched_vendor_name, null);
  await api.resolveLivePending([{ row, domain: "example.com" }], ["privacy_notice"]);
  assert.equal(calls.length, 1);
  assert.deepEqual(Object.keys(calls[0].body).sort(), ["domain", "source_types", "vendor_name"]);
  assert.equal(calls[0].body.domain, "example.com");
  assert.equal(row.openva_resolution_status, "not_found");
  assert.equal(row.openva_live_checked, true);
  assert.equal(row.openva_catalog_publication_status, "not_applicable");
})().catch((error) => { console.error(error); process.exit(1); });
'''
    node_script = (
        _preamble()
        + f"vm.runInNewContext({json.dumps(_instrumented_source())}, context, {{ filename: 'app.js' }});\n"
        + "const api = context.__openvaLiveResolverTest;\n"
        + scenario
    )
    _run_node(node_script, tmp_path)


def test_unmatched_without_domain_requires_confirmation_and_skips_worker(tmp_path: Path):
    scenario = r'''
context.__fetchHandler = () => { throw new Error("must not call the live resolver without a domain"); };
api.setCatalogData({ vendors: [] });
(async () => {
  const indexes = api.buildLocalMatchIndexes();
  const row = await api.matchInventoryRow({ vendor_name: "No Domain Co" }, 0, indexes);
  const domain = String(row.input_domain || "").trim();
  assert.equal(domain, "");
  Object.assign(row, api.buildDomainConfirmationFields());
  assert.equal(row.openva_resolution_status, "domain_confirmation_required");
  assert.equal(row.openva_live_checked, false);
})().catch((error) => { console.error(error); process.exit(1); });
'''
    node_script = (
        _preamble()
        + f"vm.runInNewContext({json.dumps(_instrumented_source())}, context, {{ filename: 'app.js' }});\n"
        + "const api = context.__openvaLiveResolverTest;\n"
        + scenario
    )
    _run_node(node_script, tmp_path)


def test_duplicate_domains_use_one_live_request(tmp_path: Path):
    scenario = r'''
let calls = 0;
context.__fetchHandler = async () => {
  calls += 1;
  return {
    ok: true,
    json: async () => ({
      vendor: { official_domain: "dupe.example" },
      sources: [{ source_type: "security_page", status: "newly_discovered", source_url: "https://dupe.example/security" }],
    }),
  };
};
(async () => {
  const rowA = { input_vendor_name: "Dupe A", input_domain: "dupe.example", source_urls: {} };
  const rowB = { input_vendor_name: "Dupe B", input_domain: "DUPE.example", source_urls: {} };
  await api.resolveLivePending(
    [{ row: rowA, domain: "dupe.example" }, { row: rowB, domain: "DUPE.example" }],
    ["security_page"],
  );
  assert.equal(calls, 1, "two rows sharing a domain (case-insensitive) must trigger one request");
  assert.equal(rowA.openva_resolution_status, "newly_discovered");
  assert.equal(rowB.openva_resolution_status, "newly_discovered");
  assert.equal(rowA.security_page_url, "https://dupe.example/security");
  assert.equal(rowB.security_page_url, "https://dupe.example/security");
})().catch((error) => { console.error(error); process.exit(1); });
'''
    node_script = (
        _preamble()
        + f"vm.runInNewContext({json.dumps(_instrumented_source())}, context, {{ filename: 'app.js' }});\n"
        + "const api = context.__openvaLiveResolverTest;\n"
        + scenario
    )
    _run_node(node_script, tmp_path)


def test_live_resolution_is_bounded_to_two_concurrent_requests(tmp_path: Path):
    scenario = r'''
let inFlight = 0;
let maxInFlight = 0;
context.__fetchHandler = async () => {
  inFlight += 1;
  maxInFlight = Math.max(maxInFlight, inFlight);
  await new Promise((resolve) => setTimeout(resolve, 10));
  inFlight -= 1;
  return {
    ok: true,
    json: async () => ({ vendor: { official_domain: "x.example" }, sources: [] }),
  };
};
(async () => {
  const pending = ["a", "b", "c", "d", "e"].map((label) => ({
    row: { input_vendor_name: label, input_domain: `${label}.example`, source_urls: {} },
    domain: `${label}.example`,
  }));
  await api.resolveLivePending(pending, ["privacy_notice"]);
  assert.ok(maxInFlight <= 2, `expected at most 2 concurrent live requests, saw ${maxInFlight}`);
  pending.forEach(({ row }) => assert.equal(row.openva_resolution_status, "not_found"));
})().catch((error) => { console.error(error); process.exit(1); });
'''
    node_script = (
        _preamble()
        + f"vm.runInNewContext({json.dumps(_instrumented_source())}, context, {{ filename: 'app.js' }});\n"
        + "const api = context.__openvaLiveResolverTest;\n"
        + scenario
    )
    _run_node(node_script, tmp_path)


def test_newly_discovered_result_never_claims_catalog_membership(tmp_path: Path):
    scenario = r'''
context.__fetchHandler = async () => ({
  ok: true,
  json: async () => ({
    vendor: { official_domain: "newvendor.example" },
    sources: [
      { source_type: "privacy_notice", status: "newly_discovered", source_url: "https://newvendor.example/privacy" },
      { source_type: "dpa", status: "not_found", source_url: null },
    ],
  }),
});
(async () => {
  const row = { input_vendor_name: "New Vendor", input_domain: "newvendor.example", matched_vendor_name: null, source_urls: {} };
  await api.resolveLivePending([{ row, domain: "newvendor.example" }], ["privacy_notice", "dpa"]);
  assert.equal(row.openva_resolution_status, "newly_discovered");
  assert.equal(row.openva_result_origin, "live_discovery");
  assert.equal(row.openva_catalog_publication_status, "pending_catalog_publication");
  assert.equal(row.matched_vendor_name, null, "a live discovery must never populate matched_vendor_name");
  assert.equal(row.official_domain, "newvendor.example");
  assert.equal(row.privacy_notice_url, "https://newvendor.example/privacy");
  assert.equal(row.dpa_url, null);
  assert.ok(!/canonical/i.test(row.openva_resolution_message));
})().catch((error) => { console.error(error); process.exit(1); });
'''
    node_script = (
        _preamble()
        + f"vm.runInNewContext({json.dumps(_instrumented_source())}, context, {{ filename: 'app.js' }});\n"
        + "const api = context.__openvaLiveResolverTest;\n"
        + scenario
    )
    _run_node(node_script, tmp_path)


def test_worker_failure_isolates_the_row_and_does_not_block_the_rest(tmp_path: Path):
    scenario = r'''
context.__fetchHandler = async (url, options) => {
  const body = JSON.parse(options.body);
  if (body.domain === "down.example") {
    throw new Error("network unreachable");
  }
  return {
    ok: true,
    json: async () => ({
      vendor: { official_domain: body.domain },
      sources: [{ source_type: "privacy_notice", status: "newly_discovered", source_url: `https://${body.domain}/privacy` }],
    }),
  };
};
(async () => {
  const failing = { input_vendor_name: "Down Co", input_domain: "down.example", source_urls: {} };
  const healthy = { input_vendor_name: "Up Co", input_domain: "up.example", source_urls: {} };
  await api.resolveLivePending(
    [{ row: failing, domain: "down.example" }, { row: healthy, domain: "up.example" }],
    ["privacy_notice"],
  );
  assert.equal(failing.openva_resolution_status, "live_resolution_error");
  assert.equal(failing.openva_live_checked, true);
  assert.match(failing.openva_resolution_message, /Live discovery failed/);
  assert.equal(healthy.openva_resolution_status, "newly_discovered");
  assert.equal(healthy.privacy_notice_url, "https://up.example/privacy");
})().catch((error) => { console.error(error); process.exit(1); });
'''
    node_script = (
        _preamble()
        + f"vm.runInNewContext({json.dumps(_instrumented_source())}, context, {{ filename: 'app.js' }});\n"
        + "const api = context.__openvaLiveResolverTest;\n"
        + scenario
    )
    _run_node(node_script, tmp_path)


def test_source_types_sent_are_bounded_to_worker_supported_set(tmp_path: Path):
    scenario = r'''
context.document.querySelectorAll = (selector) => {
  if (selector.includes("data-source-pack-field")) {
    const boxes = [
      "dpa", "privacy_notice", "subprocessors_list", "trust_center", "security_page", "status_page",
      "compliance_page", "certification_reference",
    ].map((value) => ({ dataset: { sourcePackField: value } }));
    return boxes;
  }
  return [];
};
const selected = api.selectedLiveSourceTypes();
assert.ok(selected.length <= 5, "at most 5 source types may be sent per live request");
selected.forEach((type) => {
  assert.ok(
    ["privacy_notice", "dpa", "security_page", "subprocessors_list", "trust_center", "status_page"].includes(type),
    `${type} is not a worker-supported source type`,
  );
});
assert.ok(!selected.includes("compliance_page"));
assert.ok(!selected.includes("certification_reference"));
'''
    node_script = (
        _preamble()
        + f"vm.runInNewContext({json.dumps(_instrumented_source())}, context, {{ filename: 'app.js' }});\n"
        + "const api = context.__openvaLiveResolverTest;\n"
        + scenario
    )
    _run_node(node_script, tmp_path)


def _layered_source() -> str:
    # Build order the compiled site actually uses (site/build.py): app.js loads first,
    # ui-fixes.js replaces the resolver controls and installs its own click handler,
    # resolver-source-availability.js (build-injected) re-overrides browserResultPackRow
    # last. A test against app.js alone cannot catch a wiring gap in the later layers --
    # that gap is exactly what shipped in PR #750 and went undetected until live
    # verification, so this test loads all three together, matching production.
    app_js = (SITE_SRC / "app.js").read_text(encoding="utf-8")
    ui_fixes_js = (SITE_SRC / "ui-fixes.js").read_text(encoding="utf-8")
    resolver_availability_js = (SITE_SRC / "resolver-source-availability.js").read_text(encoding="utf-8")
    return "\n".join([app_js, ui_fixes_js, resolver_availability_js])


_LAYERED_HARNESS_PREAMBLE = r'''
const vm = require("node:vm");
const assert = require("node:assert/strict");

const elementRegistry = new Map();
function stableElement(id) {
  if (!elementRegistry.has(id)) {
    const listeners = {};
    const el = {
      id,
      dataset: {},
      disabled: false,
      checked: false,
      files: [],
      value: "",
      classList: { add() {}, remove() {}, contains: () => false },
      style: {},
      _text: "",
      get textContent() { return this._text; },
      set textContent(v) { this._text = v; },
      set innerHTML(_v) {},
      addEventListener(event, cb) {
        listeners[event] = listeners[event] || [];
        listeners[event].push(cb);
      },
      listenersFor(event) { return listeners[event] || []; },
      querySelector: () => null,
      querySelectorAll: () => [],
      replaceWith: () => {},
      cloneNode: () => stableElement(`${id}-clone`),
      closest: () => null,
      setAttribute: () => {},
      replaceChildren: () => {},
      appendChild: () => {},
      append: () => {},
    };
    elementRegistry.set(id, el);
  }
  return elementRegistry.get(id);
}

const domContentLoadedCallbacks = [];
const context = {
  console,
  URL,
  AbortController,
  FileReader: undefined,
  setTimeout,
  clearTimeout,
  setInterval,
  clearInterval,
  addEventListener: (event, cb) => { if (event === "DOMContentLoaded") domContentLoadedCallbacks.push(cb); },
  location: { hash: "", origin: "https://thedanieltan.github.io", pathname: "/" },
  localStorage: { getItem: () => null, setItem: () => {} },
  document: {
    documentElement: { dataset: {}, removeAttribute: () => {} },
    querySelector: () => null,
    querySelectorAll: () => [],
    getElementById: (id) => stableElement(id),
    addEventListener: (event, cb) => { if (event === "DOMContentLoaded") domContentLoadedCallbacks.push(cb); },
    head: { appendChild: () => {} },
    createElement: () => stableElement(`created-${Math.random()}`),
  },
  fetch: (url, options) => {
    if (typeof url === "string" && url.startsWith("data/")) {
      return new Promise(() => {}); // bootstrap/availability fetches never resolve; harmless.
    }
    return context.__fetchHandler(url, options);
  },
};
context.window = context;
context.globalThis = context;
'''


def test_full_layered_stack_wires_live_resolution_into_the_active_click_handler(tmp_path: Path):
    scenario = r'''
let calls = [];
context.__fetchHandler = async (url, options) => {
  calls.push({ url, body: JSON.parse(options.body) });
  return {
    ok: true,
    json: async () => ({
      vendor: { official_domain: "resend.com" },
      sources: [{ source_type: "privacy_notice", status: "newly_discovered", source_url: "https://resend.com/privacy" }],
    }),
  };
};

api.setCatalogData({
  vendors: [
    { vendor_id: "adobe", display_name: "Adobe", legal_name: "Adobe Inc.", official_domains: ["adobe.com"], detail_path: "data/vendors/adobe.json" },
  ],
});

domContentLoadedCallbacks.forEach((cb) => cb());

const fileInput = stableElement("inventory-file");
assert.ok(fileInput.listenersFor("change").length, "ui-fixes.js must attach its own file-change listener");
const runButton = stableElement("run-local-match");
assert.ok(runButton.listenersFor("click").length, "ui-fixes.js must attach its own click listener");

// Bypass real File/DataTransfer (unavailable in a Node vm) and seed inventory rows directly,
// exactly as ui-fixes.js's change handler would have after parsing a real CSV.
api.setLocalInventoryRows([
  { vendor_name: "Adobe", domain: "adobe.com" },
  { vendor_name: "Resend", domain: "resend.com" },
]);

stableElement("enable-live-resolution").checked = true;

(async () => {
  await runButton.listenersFor("click")[0]();

  assert.equal(calls.length, 1, "the live resolver must be called exactly once (for the unmatched Resend row)");
  assert.equal(calls[0].body.domain, "resend.com");

  const rows = api.getLocalMatchRows();
  assert.equal(rows.length, 2);
  const adobeRow = rows.find((r) => r.input_vendor_name === "Adobe");
  const resendRow = rows.find((r) => r.input_vendor_name === "Resend");

  assert.equal(adobeRow.openva_resolution_status, "catalog_match");
  assert.equal(adobeRow.openva_result_origin, "published_catalog");

  assert.equal(resendRow.openva_resolution_status, "newly_discovered");
  assert.equal(resendRow.openva_result_origin, "live_discovery");
  assert.equal(resendRow.openva_catalog_publication_status, "pending_catalog_publication");
  assert.equal(resendRow.privacy_notice_url, "https://resend.com/privacy");

  const csv = resultPackCsv([{ vendor_name: "Adobe", domain: "adobe.com" }, { vendor_name: "Resend", domain: "resend.com" }], rows);
  assert.ok(csv.includes("openva_resolution_status"), "the actually-active CSV serializer must emit the new columns");
  assert.ok(csv.includes("newly_discovered"));
})().catch((error) => { console.error(error); process.exit(1); });
'''
    export_block = """
globalThis.__openvaLiveResolverTest = {
  setCatalogData: (data) => { catalogData = data; },
  setLocalInventoryRows: (rows) => { localInventoryRows = rows; },
  getLocalMatchRows: () => localMatchRows,
};
"""
    node_script = (
        _LAYERED_HARNESS_PREAMBLE
        + f"vm.runInNewContext({json.dumps(_layered_source() + export_block)}, context, {{ filename: 'layered-site.js' }});\n"
        + "const api = context.__openvaLiveResolverTest;\n"
        + scenario
    )
    _run_node(node_script, tmp_path)
