/**
 * OpenVA for Google Sheets — pure transformation logic.
 *
 * This file contains ONLY deterministic, side-effect-free helpers. It must not call
 * SpreadsheetApp, PropertiesService, UrlFetchApp, Utilities, Logger, or any other Google
 * service. Keeping it pure makes every rule below testable under Node's built-in test
 * runner (see test/core.test.mjs) and keeps the Apps Script adapters thin.
 *
 * Boundary reminder: results returned by the OpenVA API are public-source references
 * cached to the service's loaded catalogue snapshot. They are not advice, not live
 * verification, not compliance approval, and not a vendor-risk judgement.
 */

// Canonical vendor-identity fields accepted by POST /v1/enrich. Nothing else is ever sent.
var OPENVA_IDENTITY_FIELDS = [
  'vendor_name',
  'domain',
  'business_entity_name',
  'registration_number',
];

// Document-property key holding the configured OpenVA API base URL. This is a public
// service URL, not a secret.
var OPENVA_API_BASE_URL_KEY = 'OPENVA_API_BASE_URL';

// The only two API paths this client is permitted to call.
var OPENVA_CATALOG_META_PATH = '/v1/catalog/meta';
var OPENVA_ENRICH_PATH = '/v1/enrich';

// Bounded batch size for a single /v1/enrich request. Apps Script execution time and
// request size are limited; large sheets are sent as sequential bounded batches.
var OPENVA_BATCH_SIZE = 100;

// Transient HTTP statuses that may be retried with bounded exponential backoff.
var OPENVA_RETRYABLE_STATUSES = [429, 502, 503, 504];
var OPENVA_MAX_RETRIES = 2;

// Stable OpenVA output columns, reusing the API's "spreadsheet" projection. This exact
// order is written back into the sheet unless the merged API contract differs.
var OPENVA_OUTPUT_COLUMNS = [
  'openva_match_status',
  'openva_vendor_id',
  'openva_vendor_name',
  'openva_dpa',
  'openva_subprocessors',
  'openva_privacy_notice',
  'openva_security',
  'openva_trust_center',
  'openva_compliance',
  'openva_last_observed_at',
  'openva_snapshot_digest',
  'openva_notes',
];

// Centrally defined alias map for common spreadsheet headers. Aliases are normalized the
// same way as sheet headers, so spacing/hyphen/underscore/case variants all collapse to
// one canonical field. Do NOT infer identity from arbitrary unrelated columns.
var OPENVA_HEADER_ALIASES = {
  vendor_name: ['vendor_name', 'vendor name', 'vendor', 'supplier', 'supplier_name', 'supplier name'],
  domain: ['domain', 'vendor_domain', 'vendor domain', 'website', 'website domain'],
  business_entity_name: ['business_entity_name', 'business entity name', 'legal_name', 'legal name'],
  registration_number: [
    'registration_number',
    'registration number',
    'company_registration_number',
    'company registration number',
  ],
};

/**
 * Normalize a header (or alias): trim, lowercase, and collapse any run of whitespace,
 * hyphens, and underscores into a single underscore. "Vendor Name", "vendor-name" and
 * "vendor_name" all normalize to "vendor_name".
 */
function normalizeHeader(value) {
  if (value === null || value === undefined) {
    return '';
  }
  return String(value)
    .trim()
    .toLowerCase()
    .replace(/[\s_\-]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

/**
 * Build the normalized-alias -> canonical-field lookup once. A normalized alias that
 * would map to two different canonical fields is a programming error and throws.
 */
function buildAliasLookup() {
  var lookup = {};
  Object.keys(OPENVA_HEADER_ALIASES).forEach(function (canonical) {
    OPENVA_HEADER_ALIASES[canonical].forEach(function (alias) {
      var key = normalizeHeader(alias);
      if (lookup[key] !== undefined && lookup[key] !== canonical) {
        throw new Error('Alias map conflict for "' + key + '"');
      }
      lookup[key] = canonical;
    });
  });
  return lookup;
}

/**
 * Normalize and validate the configured API base URL.
 *
 * Accepts only an HTTPS origin or HTTPS base path. Rejects non-HTTPS schemes, embedded
 * credentials, fragments, query strings, and empty values. Normalizes a trailing slash
 * away (https://openva.example/ -> https://openva.example). Never silently falls back to
 * a default endpoint.
 *
 * @returns {{ok: true, url: string} | {ok: false, error: string}}
 */
function normalizeBaseUrl(raw) {
  if (raw === null || raw === undefined) {
    return { ok: false, error: 'No API endpoint configured.' };
  }
  var value = String(raw).trim();
  if (value === '') {
    return { ok: false, error: 'No API endpoint configured.' };
  }
  if (!/^https:\/\//i.test(value)) {
    return { ok: false, error: 'Endpoint must be an https:// URL.' };
  }
  // Reject obvious non-HTTP schemes embedded as a prefix (defence-in-depth; the https
  // check above already excludes them, but keep an explicit guard for clarity).
  if (/^(javascript|data|file|ftp):/i.test(value)) {
    return { ok: false, error: 'Unsupported URL scheme.' };
  }
  if (value.indexOf('@') !== -1) {
    return { ok: false, error: 'Endpoint must not contain a username or password.' };
  }
  if (value.indexOf('#') !== -1) {
    return { ok: false, error: 'Endpoint must not contain a fragment.' };
  }
  if (value.indexOf('?') !== -1) {
    return { ok: false, error: 'Endpoint must not contain a query string.' };
  }
  // Host must be present after the scheme.
  var afterScheme = value.slice('https://'.length);
  if (afterScheme === '' || afterScheme.charAt(0) === '/') {
    return { ok: false, error: 'Endpoint is missing a host.' };
  }
  // Strip a single trailing slash so path joining is predictable.
  var normalized = value.replace(/\/+$/, '');
  return { ok: true, url: normalized };
}

/** Join a normalized base URL with an API path (path begins with "/"). */
function joinUrl(baseUrl, path) {
  return baseUrl + path;
}

/**
 * Resolve sheet header cells to canonical input columns.
 *
 * Returns the 0-based column index for each recognized canonical field. Two distinct
 * header cells that resolve to the same canonical field are ambiguous and rejected, so
 * "Vendor Name" and "vendor_name" cannot silently collide.
 *
 * @returns {{ok: true, columns: Object} | {ok: false, error: string}}
 */
function resolveInputColumns(headerRow) {
  var lookup = buildAliasLookup();
  var columns = {};
  var sourceHeader = {};
  for (var i = 0; i < headerRow.length; i++) {
    var normalized = normalizeHeader(headerRow[i]);
    if (normalized === '') {
      continue;
    }
    var canonical = lookup[normalized];
    if (canonical === undefined) {
      continue;
    }
    if (columns[canonical] !== undefined) {
      return {
        ok: false,
        error:
          'Ambiguous headers: "' +
          sourceHeader[canonical] +
          '" and "' +
          headerRow[i] +
          '" both map to ' +
          canonical +
          '. Rename one column and retry.',
      };
    }
    columns[canonical] = i;
    sourceHeader[canonical] = headerRow[i];
  }
  return { ok: true, columns: columns };
}

/** Coerce a sheet cell to trimmed text. Numbers (e.g. registration numbers) become strings. */
function cellToText(value) {
  if (value === null || value === undefined) {
    return '';
  }
  return String(value).trim();
}

/**
 * Build the enrichment payload object for one sheet row.
 *
 * Includes only the four supported identity fields plus a string row_id. Fields with no
 * value become null. Returns null when every identity field is blank (the row is skipped
 * and never sent). Sheet names, spreadsheet ids, formulas, notes, user email and
 * unrelated columns are never included.
 *
 * @returns {Object | null}
 */
function buildVendorPayload(rowValues, columns, rowNumber) {
  var vendor = { row_id: String(rowNumber) };
  var hasIdentity = false;
  for (var f = 0; f < OPENVA_IDENTITY_FIELDS.length; f++) {
    var field = OPENVA_IDENTITY_FIELDS[f];
    var value = null;
    if (columns[field] !== undefined) {
      var text = cellToText(rowValues[columns[field]]);
      if (text !== '') {
        value = text;
        hasIdentity = true;
      }
    }
    vendor[field] = value;
  }
  return hasIdentity ? vendor : null;
}

/** Split an ordered array into bounded chunks, preserving order and duplicates. */
function chunkRows(items, size) {
  var batchSize = size && size > 0 ? size : OPENVA_BATCH_SIZE;
  var chunks = [];
  for (var i = 0; i < items.length; i += batchSize) {
    chunks.push(items.slice(i, i + batchSize));
  }
  return chunks;
}

/** True when an HTTP status is a bounded-retry transient status. */
function isRetryableStatus(status) {
  return OPENVA_RETRYABLE_STATUSES.indexOf(status) !== -1;
}

/**
 * Validate one /v1/enrich response body against the row_ids submitted in that batch.
 *
 * Enforces the response contract before any sheet mutation: result count equals the
 * submitted count, order matches, every row_id corresponds, every result carries a
 * "spreadsheet" projection object, and the snapshot digest is present. Malformed results
 * are never silently realigned.
 *
 * @returns {{ok: true, snapshotDigest: string, results: Array} | {ok: false, error: string}}
 */
function validateEnrichmentResponse(parsed, expectedRowIds) {
  if (parsed === null || typeof parsed !== 'object') {
    return { ok: false, error: 'API returned an unexpected response body.' };
  }
  var snapshot = parsed.snapshot;
  if (snapshot === null || typeof snapshot !== 'object' || !snapshot.snapshot_digest) {
    return { ok: false, error: 'API response is missing a snapshot digest.' };
  }
  var results = parsed.results;
  if (!Array.isArray(results)) {
    return { ok: false, error: 'API response is missing a results array.' };
  }
  if (results.length !== expectedRowIds.length) {
    return {
      ok: false,
      error:
        'API returned ' +
        results.length +
        ' results for ' +
        expectedRowIds.length +
        ' submitted rows.',
    };
  }
  for (var i = 0; i < results.length; i++) {
    var result = results[i];
    if (result === null || typeof result !== 'object') {
      return { ok: false, error: 'API returned a malformed result for row ' + expectedRowIds[i] + '.' };
    }
    if (String(result.row_id) !== String(expectedRowIds[i])) {
      return {
        ok: false,
        error:
          'API result order mismatch: expected row ' +
          expectedRowIds[i] +
          ' but received ' +
          result.row_id +
          '.',
      };
    }
    if (result.spreadsheet === null || typeof result.spreadsheet !== 'object') {
      return { ok: false, error: 'API result for row ' + expectedRowIds[i] + ' is missing a spreadsheet projection.' };
    }
  }
  return { ok: true, snapshotDigest: String(snapshot.snapshot_digest), results: results };
}

/**
 * Merge already-validated batch responses into one ordered result list.
 *
 * Every batch must share the same snapshot digest; a change means the catalogue moved
 * mid-operation and the whole operation must abort before writing, so the user reruns
 * against a single consistent snapshot.
 *
 * @param {Array<{snapshotDigest: string, results: Array}>} validatedBatches
 * @returns {{ok: true, snapshotDigest: string, results: Array} | {ok: false, error: string}}
 */
function mergeBatchResponses(validatedBatches) {
  if (!Array.isArray(validatedBatches) || validatedBatches.length === 0) {
    return { ok: false, error: 'No enrichment results to merge.' };
  }
  var digest = validatedBatches[0].snapshotDigest;
  var merged = [];
  for (var i = 0; i < validatedBatches.length; i++) {
    if (validatedBatches[i].snapshotDigest !== digest) {
      return {
        ok: false,
        error:
          'The catalogue snapshot changed during enrichment (a multi-batch run mixed two ' +
          'snapshots). No results were written. Please rerun the enrichment.',
      };
    }
    merged = merged.concat(validatedBatches[i].results);
  }
  return { ok: true, snapshotDigest: digest, results: merged };
}

/**
 * Neutralize spreadsheet formula injection. Any string beginning with =, +, -, or @ is
 * prefixed with a single quote so the sheet treats it as literal text. Plain https URLs
 * (which begin with "h") pass through unchanged and remain usable. Null/undefined become
 * an empty string so cells are blank rather than the text "null" or "undefined".
 */
function safeCellValue(value) {
  if (value === null || value === undefined) {
    return '';
  }
  if (typeof value !== 'string') {
    return value;
  }
  if (value.length > 0 && '=+-@'.indexOf(value.charAt(0)) !== -1) {
    return "'" + value;
  }
  return value;
}

/**
 * Map one API "spreadsheet" projection to an ordered output-row array, applying formula
 * protection and turning missing values into blank cells.
 */
function mapProjectionToOutputRow(projection, outputColumns) {
  var columns = outputColumns || OPENVA_OUTPUT_COLUMNS;
  return columns.map(function (column) {
    var raw = projection && projection[column] !== undefined ? projection[column] : null;
    return safeCellValue(raw);
  });
}

/** Group a list of column indices into ascending contiguous runs, e.g. [1,2,4,5] -> [[1,2],[4,5]]. */
function groupContiguous(indices) {
  var sorted = indices.slice().sort(function (a, b) {
    return a - b;
  });
  var runs = [];
  var current = null;
  for (var i = 0; i < sorted.length; i++) {
    if (current === null || sorted[i] !== current[current.length - 1] + 1) {
      current = [sorted[i]];
      runs.push(current);
    } else {
      current.push(sorted[i]);
    }
  }
  return runs;
}

/**
 * Plan where OpenVA output columns live in the header.
 *
 * Existing OpenVA columns are reused by normalized header match; missing ones are
 * appended to the right of existing data. Non-OpenVA columns are never moved or
 * overwritten.
 *
 * @returns {{assignments: Object, totalWidth: number, headerWrites: Array<{index:number,value:string}>}}
 */
function planOutputColumns(headerRow, outputColumns) {
  var columns = outputColumns || OPENVA_OUTPUT_COLUMNS;
  var normalized = headerRow.map(normalizeHeader);
  var assignments = {};
  var headerWrites = [];
  var nextIndex = headerRow.length;
  columns.forEach(function (column) {
    var existing = normalized.indexOf(column);
    if (existing !== -1) {
      assignments[column] = existing;
    } else {
      assignments[column] = nextIndex;
      headerWrites.push({ index: nextIndex, value: column });
      nextIndex += 1;
    }
  });
  return { assignments: assignments, totalWidth: nextIndex, headerWrites: headerWrites };
}

// Export pure helpers for the Node test runner. Apps Script has no `module` global, so
// this block is skipped at runtime in Google Sheets and changes nothing there.
if (typeof module === 'object' && module.exports) {
  module.exports = {
    OPENVA_IDENTITY_FIELDS: OPENVA_IDENTITY_FIELDS,
    OPENVA_API_BASE_URL_KEY: OPENVA_API_BASE_URL_KEY,
    OPENVA_CATALOG_META_PATH: OPENVA_CATALOG_META_PATH,
    OPENVA_ENRICH_PATH: OPENVA_ENRICH_PATH,
    OPENVA_BATCH_SIZE: OPENVA_BATCH_SIZE,
    OPENVA_RETRYABLE_STATUSES: OPENVA_RETRYABLE_STATUSES,
    OPENVA_MAX_RETRIES: OPENVA_MAX_RETRIES,
    OPENVA_OUTPUT_COLUMNS: OPENVA_OUTPUT_COLUMNS,
    OPENVA_HEADER_ALIASES: OPENVA_HEADER_ALIASES,
    normalizeHeader: normalizeHeader,
    buildAliasLookup: buildAliasLookup,
    normalizeBaseUrl: normalizeBaseUrl,
    joinUrl: joinUrl,
    resolveInputColumns: resolveInputColumns,
    cellToText: cellToText,
    buildVendorPayload: buildVendorPayload,
    chunkRows: chunkRows,
    isRetryableStatus: isRetryableStatus,
    validateEnrichmentResponse: validateEnrichmentResponse,
    mergeBatchResponses: mergeBatchResponses,
    safeCellValue: safeCellValue,
    mapProjectionToOutputRow: mapProjectionToOutputRow,
    groupContiguous: groupContiguous,
    planOutputColumns: planOutputColumns,
  };
}
