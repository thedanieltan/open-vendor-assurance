/**
 * OpenVA for Google Sheets — menu, prompts, and user feedback.
 *
 * This file owns all UI. It surfaces toasts and dialogs for configuration, connection
 * tests, and enrichment outcomes. It never exposes stack traces, request payloads, vendor
 * identities, or raw HTML error pages to the user, and it never logs them.
 *
 * Results are public-source references cached to the service's loaded catalogue snapshot.
 * They are not advice, not live verification, and not compliance, security, or
 * vendor-risk approval. An unmatched vendor means no catalogue match was found — never
 * that the vendor is unsafe, non-compliant, or lacks a DPA.
 */

/** Installable-free simple trigger: build the OpenVA menu when the spreadsheet opens. */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('OpenVA')
    .addItem('Configure API endpoint', 'openvaConfigureEndpoint')
    .addItem('Configure source types', 'openvaConfigureSourceTypes')
    .addItem('Test API connection', 'openvaTestConnection')
    .addSeparator()
    .addItem('Enrich selected rows', 'openvaEnrichSelectedRows')
    .addItem('Enrich active sheet', 'openvaEnrichActiveSheet')
    .addSeparator()
    .addItem('Help', 'openvaShowHelp')
    .addToUi();
}

function openvaToast(message, title) {
  SpreadsheetApp.getActiveSpreadsheet().toast(message, title || 'OpenVA', 8);
}

function openvaAlert(message, title) {
  SpreadsheetApp.getUi().alert(title || 'OpenVA', message, SpreadsheetApp.getUi().ButtonSet.OK);
}

/** OpenVA → Configure API endpoint. Stores a validated HTTPS base URL (public, not secret). */
function openvaConfigureEndpoint() {
  var ui = SpreadsheetApp.getUi();
  var current = PropertiesService.getDocumentProperties().getProperty(OPENVA_API_BASE_URL_KEY) || '';
  var response = ui.prompt(
    'Configure OpenVA API endpoint',
    'Enter the HTTPS base URL of an OpenVA deployment with public read access enabled' +
      (current ? '\n\nCurrent: ' + current : '') +
      '\n\nExample: https://openva.example',
    ui.ButtonSet.OK_CANCEL
  );
  if (response.getSelectedButton() !== ui.Button.OK) {
    return;
  }
  var normalized = normalizeBaseUrl(response.getResponseText());
  if (!normalized.ok) {
    openvaAlert(normalized.error, 'Invalid endpoint');
    return;
  }
  PropertiesService.getDocumentProperties().setProperty(OPENVA_API_BASE_URL_KEY, normalized.url);
  openvaToast('Endpoint saved: ' + normalized.url);
}

/** OpenVA → Configure source types. Opens a small checkbox dialog. */
function openvaConfigureSourceTypes() {
  var html = HtmlService.createHtmlOutputFromFile('SourceTypes').setWidth(360).setHeight(360);
  SpreadsheetApp.getUi().showModalDialog(html, 'Configure source types');
}

/** Server callback for the source-types dialog: current supported list, labels, selection. */
function openvaGetSourceTypesConfig() {
  var stored = PropertiesService.getDocumentProperties().getProperty(OPENVA_SOURCE_TYPES_KEY);
  return {
    supported: OPENVA_SUPPORTED_SOURCE_TYPES,
    labels: OPENVA_SOURCE_TYPE_LABELS,
    selected: resolveStoredSourceTypes(stored),
  };
}

/** Server callback for the source-types dialog: validate and persist the selection. */
function openvaSaveSourceTypes(selected) {
  var normalized = normalizeSourceTypes(selected || []);
  if (!normalized.ok) {
    return { ok: false, error: normalized.error };
  }
  PropertiesService.getDocumentProperties().setProperty(
    OPENVA_SOURCE_TYPES_KEY,
    JSON.stringify(normalized.sourceTypes)
  );
  return { ok: true, sourceTypes: normalized.sourceTypes };
}

/** OpenVA → Test API connection. Calls GET /v1/catalog/meta and summarizes the snapshot. */
function openvaTestConnection() {
  var base = getConfiguredBaseUrl();
  if (!base.ok) {
    openvaAlert(base.error + ' Use OpenVA → Configure API endpoint.', 'Not configured');
    return;
  }
  var result = testApiConnection(base.url);
  if (!result.ok) {
    openvaAlert(result.error, 'Connection failed');
    return;
  }
  var snapshot = result.snapshot;
  openvaAlert(
    'Connected to OpenVA.\n\n' +
      'Profile: ' + snapshot.profile_id + '\n' +
      'Vendors: ' + snapshot.vendor_count + '\n' +
      'Sources: ' + snapshot.source_count + '\n' +
      'Snapshot digest: ' + snapshot.snapshot_digest + '\n\n' +
      'Results are public-source references cached to this catalogue snapshot. This is not ' +
      'live verification or compliance approval.',
    'Connection OK'
  );
}

/** OpenVA → Enrich selected rows. */
function openvaEnrichSelectedRows() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  openvaRunEnrichment(selectedRowNumbers(sheet));
}

/** OpenVA → Enrich active sheet. */
function openvaEnrichActiveSheet() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  openvaRunEnrichment(activeSheetRowNumbers(sheet));
}

/** Shared enrichment runner: invokes the orchestrator and reports the outcome via toast. */
function openvaRunEnrichment(rowNumbers) {
  if (!rowNumbers || rowNumbers.length === 0) {
    openvaAlert('Select one or more data rows (below the header) first.', 'Nothing selected');
    return;
  }
  openvaToast('Enriching ' + rowNumbers.length + ' row(s)…', 'OpenVA');
  var summary = enrichRows(rowNumbers);
  if (!summary.ok) {
    openvaAlert(summary.error, 'Enrichment stopped');
    return;
  }
  if (summary.enriched === 0) {
    openvaToast('No rows had a supported vendor-identity value. ' + summary.skipped + ' blank row(s) skipped.');
    return;
  }
  openvaAlert(
    'Enriched ' + summary.enriched + ' row(s).\n' +
      'Skipped ' + summary.skipped + ' blank row(s).\n' +
      'Snapshot digest: ' + summary.snapshotDigest + '\n\n' +
      'Results are public-source references cached to this catalogue snapshot — not advice, ' +
      'not live verification, not compliance or vendor-risk approval. An unmatched vendor ' +
      'means no catalogue match was found.',
    'Enrichment complete'
  );
}

/** OpenVA → Help. */
function openvaShowHelp() {
  var html = HtmlService.createHtmlOutputFromFile('Help').setWidth(420).setHeight(480);
  SpreadsheetApp.getUi().showModalDialog(html, 'OpenVA help');
}
