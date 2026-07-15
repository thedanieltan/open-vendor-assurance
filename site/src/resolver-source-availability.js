(() => {
  const RESOLVER_SOURCE_AVAILABILITY_VERSION = "catalog-snapshot-v1";
  const CONTROLLED_SOURCE_TYPES = [
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
  ];
  const DEFAULT_SELECTED_TYPES = new Set([
    "dpa",
    "privacy_notice",
    "subprocessors_list",
    "security_page",
    "trust_center",
  ]);

  const style = document.createElement("style");
  style.id = "openva-resolver-source-availability";
  style.textContent = `
    .source-field-grid__label {
      display: grid !important;
      grid-template-columns: auto minmax(0, 1fr) auto;
      align-items: center !important;
      gap: .45rem !important;
    }
    .source-field-grid__label small {
      color: var(--donor-muted, #64748b);
      font-family: "JetBrains Mono", ui-monospace, monospace;
      font-size: .64rem;
      font-weight: 400;
      white-space: nowrap;
    }
    .source-field-availability-note,
    .source-field-unavailable-note {
      grid-column: 1 / -1;
      margin: .4rem 0 0;
      color: var(--donor-muted, #64748b);
      font-size: .72rem;
      line-height: 1.55;
    }
    .source-field-unavailable-note {
      margin-top: 0;
    }
  `;
  document.head.appendChild(style);

  function selectedSourceTypes() {
    return [...document.querySelectorAll("#matcher-view [data-source-pack-field]:checked")]
      .map((box) => box.dataset.sourcePackField)
      .filter((sourceType) => CONTROLLED_SOURCE_TYPES.includes(sourceType));
  }

  function sourceUrlsByType(summary) {
    const urls = new Map();
    const sources = summary && Array.isArray(summary.sources) ? summary.sources : [];
    sources.forEach((source) => {
      if (
        CONTROLLED_SOURCE_TYPES.includes(source.source_type)
        && source.source_url
        && !urls.has(source.source_type)
      ) {
        urls.set(source.source_type, source.source_url);
      }
    });
    return urls;
  }

  function firstOfficialDomain(vendor) {
    if (!vendor || !Array.isArray(vendor.official_domains)) return null;
    return vendor.official_domains.find(Boolean) || null;
  }

  function availabilityAwareResultPackRow(row, inputIndex, vendor, summary = null) {
    const selected = new Set(selectedSourceTypes());
    const sourceUrls = sourceUrlsByType(summary);
    const matched = Boolean(vendor);
    const result = {
      result_pack_version:
        typeof RESULT_PACK_VERSION === "undefined" ? "2.0.0" : RESULT_PACK_VERSION,
      input_index: inputIndex,
      input_vendor_name: row.vendor_name || row.business_entity_name || null,
      input_domain: row.domain || null,
      matched_vendor_name: matched ? vendor.display_name : null,
      official_domain: matched ? firstOfficialDomain(vendor) : null,
      source_urls: {},
      trust_security_url: null,
      dpa_url: null,
      subprocessors_url: null,
      privacy_notice_url: null,
      status_page_url: null,
    };

    CONTROLLED_SOURCE_TYPES.forEach((sourceType) => {
      const url = matched && selected.has(sourceType)
        ? sourceUrls.get(sourceType) || null
        : null;
      result.source_urls[sourceType] = url;
      result[`${sourceType}_url`] = url;
    });

    result.trust_security_url = result.trust_center_url || result.security_page_url || null;
    result.subprocessors_url = result.subprocessors_list_url || null;
    return result;
  }

  function installProjection() {
    try {
      browserResultPackRow = availabilityAwareResultPackRow;
    } catch (_error) {
      window.browserResultPackRow = availabilityAwareResultPackRow;
    }
  }

  function sourceLabel(payload, sourceType) {
    return (payload.labels && payload.labels[sourceType]) || sourceType.replaceAll("_", " ");
  }

  function sourceField(payload, sourceType, checked) {
    const label = document.createElement("label");
    label.className = "source-field-grid__label";

    const input = document.createElement("input");
    input.type = "checkbox";
    input.dataset.sourcePackField = sourceType;
    input.checked = checked;

    const name = document.createElement("span");
    name.textContent = sourceLabel(payload, sourceType);

    const count = document.createElement("small");
    const records = Number(payload.counts[sourceType] || 0);
    count.textContent = `${records.toLocaleString()} ${records === 1 ? "record" : "records"}`;

    label.append(input, name, count);
    return label;
  }

  function renderAvailability(payload) {
    const fieldset = document.querySelector("#matcher-view .source-field-grid");
    if (!fieldset) return;

    const previouslySelected = new Set(selectedSourceTypes());
    const counts = payload.counts || {};
    const availableTypes = (payload.items || [])
      .filter((sourceType) => Number(counts[sourceType] || 0) > 0);
    const unavailableTypes = CONTROLLED_SOURCE_TYPES
      .filter((sourceType) => Number(counts[sourceType] || 0) === 0);
    const totalRecords = availableTypes
      .reduce((total, sourceType) => total + Number(counts[sourceType] || 0), 0);

    const legend = document.createElement("legend");
    legend.textContent = "Source types available in the current catalog";

    const fields = availableTypes.map((sourceType) => {
      const checked = previouslySelected.size
        ? previouslySelected.has(sourceType)
        : DEFAULT_SELECTED_TYPES.has(sourceType);
      return sourceField(payload, sourceType, checked);
    });

    const availabilityNote = document.createElement("p");
    availabilityNote.id = "resolver-source-availability-note";
    availabilityNote.className = "source-field-availability-note";
    availabilityNote.textContent = `${availableTypes.length} source types contain ${totalRecords.toLocaleString()} catalog records in this snapshot. A matched vendor may have only a subset; a blank download cell means no indexed URL for that vendor and source type.`;

    const unavailableNote = document.createElement("p");
    unavailableNote.className = "source-field-unavailable-note";
    unavailableNote.textContent = unavailableTypes.length
      ? `Defined by the schema but not currently indexed: ${unavailableTypes.map((sourceType) => sourceLabel(payload, sourceType)).join(", ")}.`
      : "Every schema-defined source type currently has at least one catalog record.";

    fieldset.replaceChildren(legend, ...fields, availabilityNote, unavailableNote);
    fieldset.setAttribute("aria-describedby", availabilityNote.id);

    const builder = fieldset.closest(".source-builder-card");
    const heading = builder && builder.querySelector(":scope > div > h3");
    const copy = heading && heading.nextElementSibling;
    if (heading) heading.textContent = "Choose source types that exist in this catalog snapshot.";
    if (copy) {
      copy.textContent = "The options and record counts come from the current accepted catalog. Presets only select available types; clear every option for an identity-only export.";
    }
  }

  async function install() {
    installProjection();
    const response = await fetch("data/source-types.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`source type availability returned HTTP ${response.status}`);
    const payload = await response.json();
    payload.counts = payload.counts || {};
    renderAvailability(payload);
    window.OPENVA_RESOLVER_SOURCE_AVAILABILITY_VERSION = RESOLVER_SOURCE_AVAILABILITY_VERSION;
  }

  install().catch((error) => {
    console.warn("OpenVA resolver source availability could not be installed", error);
    const fieldset = document.querySelector("#matcher-view .source-field-grid");
    if (!fieldset || fieldset.querySelector(".source-field-availability-note")) return;
    const note = document.createElement("p");
    note.className = "source-field-availability-note";
    note.textContent = "Current catalog source availability could not be loaded. Verify downloaded source columns against the catalog snapshot before use.";
    fieldset.appendChild(note);
  });
})();
