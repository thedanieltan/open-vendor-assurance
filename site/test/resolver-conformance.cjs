// Cross-runtime resolver conformance harness (Node).
//
// Proves the shared JS matcher core (site/src/openva-matcher-core.js) reproduces the
// authoritative Python core's normalization and confidence contract, using the committed
// vectors in tests/conformance/resolver-conformance.json (generated FROM the Python core).
// Fails closed (non-zero exit) on any divergence, so a normalization change on either the
// Python or the JS side cannot land silently.
//
// Run directly (`node site/test/resolver-conformance.cjs`) or via
// tests/test_resolver_js_conformance.py.
"use strict";

const path = require("node:path");
const fs = require("node:fs");

const ROOT = path.resolve(__dirname, "..", "..");
const core = require(path.join(ROOT, "site", "src", "openva-matcher-core.js"));
const suite = JSON.parse(
  fs.readFileSync(path.join(ROOT, "tests", "conformance", "resolver-conformance.json"), "utf8")
);

const problems = [];
function check(label, expected, actual) {
  if (expected !== actual) {
    problems.push(`${label}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
}

// 1. Confidence contract — the JS core must not hand-maintain a different 0.90 etc.
const contract = suite.contract;
check("contract.minimum_match_confidence", contract.minimum_match_confidence, core.MINIMUM_MATCH_CONFIDENCE);
check("contract.ambiguity_margin", contract.ambiguity_margin, core.AMBIGUITY_MARGIN);
for (const method of Object.keys(contract.method_confidence)) {
  check(`contract.method_confidence.${method}`, contract.method_confidence[method], core.METHOD_CONFIDENCE[method]);
}
check(
  "contract.legal_suffixes",
  JSON.stringify(contract.legal_suffixes.slice().sort()),
  JSON.stringify(core.LEGAL_SUFFIXES.slice().sort())
);

// 2. Normalization vectors — the JS core must reproduce every Python-computed result.
const norm = suite.normalization;
for (const vector of norm.domain) {
  check(`normalizeDomain(${JSON.stringify(vector.input)})`, vector.normalized, core.normalizeDomain(vector.input));
}
for (const vector of norm.name) {
  check(`normalizeName(${JSON.stringify(vector.input)})`, vector.normalized, core.normalizeName(vector.input));
  check(`stripLegalSuffixes(${JSON.stringify(vector.input)})`, vector.stripped, core.stripLegalSuffixes(vector.input));
}
for (const vector of norm.registration_number) {
  check(
    `normalizeRegistrationNumber(${JSON.stringify(vector.input)})`,
    vector.normalized,
    core.normalizeRegistrationNumber(vector.input)
  );
}
for (const vector of norm.jurisdiction) {
  check(`normalizeJurisdiction(${JSON.stringify(vector.input)})`, vector.normalized, core.normalizeJurisdiction(vector.input));
}

if (problems.length) {
  console.error("JS resolver conformance FAILED:");
  for (const problem of problems) {
    console.error("  - " + problem);
  }
  process.exit(1);
}
const total =
  norm.domain.length + norm.name.length + norm.registration_number.length + norm.jurisdiction.length;
console.log(`JS resolver conformance: shared core reproduces ${total} normalization vectors + contract.`);
