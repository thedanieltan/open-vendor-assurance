// GENERATED FILE — DO NOT EDIT.
// Source: config/openva-capabilities.yaml
// Regenerate: python -m tools.openva.capabilities generate
(() => {
  "use strict";
  const CAPABILITIES = Object.freeze({
    manifest_version: "1.0.0",
    contracts: Object.freeze({
      schema_version: "0.1.0",
      resolver_contract_version: "1.0.0",
      result_pack_version: "2.0.0",
    }),
    source_types: Object.freeze([
      "dpa",
      "subprocessors_list",
      "privacy_notice",
      "trust_center",
      "security_page",
      "compliance_page",
      "certification_reference",
      "terms_of_service",
      "kyc_statement",
      "aml_statement",
      "ai_terms",
      "government_request_policy",
      "transparency_report",
      "status_page",
      "other_public_source",
    ]),
    source_type_labels: Object.freeze({
      "dpa": "Data processing addendum",
      "subprocessors_list": "Subprocessor list",
      "privacy_notice": "Privacy notice",
      "trust_center": "Trust center",
      "security_page": "Security page",
      "compliance_page": "Compliance page",
      "certification_reference": "Certification reference",
      "terms_of_service": "Terms of service",
      "kyc_statement": "Know your customer statement",
      "aml_statement": "Anti-money laundering statement",
      "ai_terms": "Artificial intelligence terms",
      "government_request_policy": "Government request policy",
      "transparency_report": "Transparency report",
      "status_page": "Service status page",
      "other_public_source": "Other public source",
    }),
    availability: Object.freeze({
      discovery_supported: Object.freeze([
        "dpa",
        "subprocessors_list",
        "privacy_notice",
        "trust_center",
        "security_page",
        "compliance_page",
        "certification_reference",
        "status_page",
        "ai_terms",
      ]),
      browser_default_selected: Object.freeze([
        "dpa",
        "privacy_notice",
        "subprocessors_list",
        "security_page",
        "trust_center",
      ]),
      live_resolver_supported: Object.freeze([
        "dpa",
        "subprocessors_list",
        "privacy_notice",
        "trust_center",
        "security_page",
        "compliance_page",
        "certification_reference",
        "status_page",
        "ai_terms",
      ]),
    }),
  });
  if (typeof window !== "undefined") { window.OPENVA_CAPABILITIES = CAPABILITIES; }
  if (typeof module !== "undefined" && module.exports) { module.exports = CAPABILITIES; }
})();
