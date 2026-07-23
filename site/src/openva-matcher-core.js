// OpenVA shared matcher core — the single JavaScript source of truth for identity
// normalization, mirroring the authoritative Python core
// (openva_vendor_inventory_matcher.core). Every JavaScript runtime that normalizes a
// vendor identity — the browser resolver (app.js, ui-fixes.js) and any Worker matching
// path — MUST consume these functions rather than hand-maintain its own copy, so the
// runtimes cannot drift from each other or from Python.
//
// Parity with Python is proven by the Node conformance harness
// (site/test/resolver-conformance.cjs), which runs this module against the committed
// vectors in tests/conformance/resolver-conformance.json (generated from the Python
// core). If a normalization rule changes on either side, that harness fails closed.
//
// This module is normalization only. The full match-decision logic (candidate ranking,
// ambiguity, legal-entity fallback) is authoritative in the Python core; the browser's
// decision layer is reconciled against it in a later increment.
//
// UMD: exposes `OpenVAMatcherCore` as a global for <script> loading and as
// module.exports for Node (require).
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.OpenVAMatcherCore = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  // Confidence contract — mirrors the Python core constants. Kept here so no consumer
  // hand-writes 0.90; the conformance harness asserts these equal the Python core.
  var MINIMUM_MATCH_CONFIDENCE = 0.9;
  var AMBIGUITY_MARGIN = 0.05;
  var METHOD_CONFIDENCE = { domain_exact: 1.0, domain_subdomain: 0.95, name_exact: 0.9 };
  var LEGAL_SUFFIXES = ["co", "company", "corp", "corporation", "inc", "limited", "llc", "ltd"];
  var LEGAL_SUFFIX_SET = LEGAL_SUFFIXES.reduce(function (set, suffix) {
    set[suffix] = true;
    return set;
  }, Object.create(null));

  function asString(value) {
    return value === null || value === undefined ? "" : String(value);
  }

  // Mirror of core.normalize_name: lowercase, "&" -> " and ", non-alphanumeric -> space,
  // collapse whitespace.
  function normalizeName(value) {
    var raw = asString(value).trim().toLowerCase();
    raw = raw.split("&").join(" and ");
    raw = raw.replace(/[^a-z0-9]+/g, " ");
    return raw.split(/\s+/).filter(Boolean).join(" ");
  }

  // Mirror of core.strip_legal_suffixes.
  function stripLegalSuffixes(value) {
    var tokens = normalizeName(value).split(" ").filter(Boolean);
    while (tokens.length && LEGAL_SUFFIX_SET[tokens[tokens.length - 1]]) {
      tokens.pop();
    }
    return tokens.join(" ");
  }

  // Mirror of core.normalize_domain. Deliberately NOT URL()-based: the Python core keeps
  // the domain as-is (unicode preserved), strips scheme/userinfo/port/path/trailing-dot
  // and a leading "www.". URL() would punycode internationalized domains, diverging from
  // Python; this reproduces Python exactly.
  function normalizeDomain(value) {
    var raw = asString(value).trim().toLowerCase();
    if (!raw) {
      return "";
    }
    var domain;
    if (raw.indexOf("://") !== -1) {
      // urlsplit netloc: everything between "://" and the next "/", "?" or "#".
      var afterScheme = raw.slice(raw.indexOf("://") + 3);
      domain = afterScheme.split(/[/?#]/)[0];
    } else {
      domain = raw.split(/[/#?]/)[0];
    }
    // rsplit("@")[-1] — drop any userinfo.
    var at = domain.lastIndexOf("@");
    if (at !== -1) {
      domain = domain.slice(at + 1);
    }
    // Strip a single ":port" (leave IPv6-like multi-colon strings alone, matching Python).
    if (domain.indexOf(":") !== -1 && (domain.split(":").length - 1) === 1) {
      domain = domain.slice(0, domain.indexOf(":"));
    }
    domain = domain.trim().replace(/\.+$/, "");
    if (domain.indexOf("www.") === 0) {
      domain = domain.slice(4);
    }
    return domain;
  }

  // Mirror of core.normalize_registration_number.
  function normalizeRegistrationNumber(value) {
    return asString(value).replace(/[^A-Za-z0-9]+/g, "").toUpperCase();
  }

  // Mirror of core.normalize_jurisdiction.
  function normalizeJurisdiction(value) {
    return asString(value).trim().toUpperCase();
  }

  return {
    MINIMUM_MATCH_CONFIDENCE: MINIMUM_MATCH_CONFIDENCE,
    AMBIGUITY_MARGIN: AMBIGUITY_MARGIN,
    METHOD_CONFIDENCE: METHOD_CONFIDENCE,
    LEGAL_SUFFIXES: LEGAL_SUFFIXES.slice(),
    normalizeName: normalizeName,
    stripLegalSuffixes: stripLegalSuffixes,
    normalizeDomain: normalizeDomain,
    normalizeRegistrationNumber: normalizeRegistrationNumber,
    normalizeJurisdiction: normalizeJurisdiction,
  };
});
