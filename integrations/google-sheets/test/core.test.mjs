/**
 * Pure-function tests for the OpenVA Google Sheets integration (Core.gs).
 *
 * Uses only Node's built-in test runner and assert library — no third-party framework and
 * no runtime dependencies. Core.gs is loaded via createRequire because it ships as a .gs
 * file with a guarded CommonJS export that Apps Script ignores.
 *
 *   node --test integrations/google-sheets/test/*.test.mjs
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const Core = require(path.join(here, '..', 'src', 'Core.gs'));

// --------------------------------------------------------------------------- base URL

test('normalizeBaseUrl accepts and normalizes an HTTPS origin', () => {
  assert.deepEqual(Core.normalizeBaseUrl('https://openva.example/'), {
    ok: true,
    url: 'https://openva.example',
  });
  assert.deepEqual(Core.normalizeBaseUrl('https://openva.example'), {
    ok: true,
    url: 'https://openva.example',
  });
  assert.deepEqual(Core.normalizeBaseUrl('  https://openva.example/api/  '), {
    ok: true,
    url: 'https://openva.example/api',
  });
});

test('normalizeBaseUrl rejects non-HTTPS and unsafe schemes', () => {
  for (const bad of ['http://openva.example', 'javascript:alert(1)', 'data:text/html,x', 'ftp://x', 'file:///etc']) {
    assert.equal(Core.normalizeBaseUrl(bad).ok, false, bad);
  }
});

test('normalizeBaseUrl rejects credentials, query and fragment', () => {
  assert.equal(Core.normalizeBaseUrl('https://user:pass@openva.example').ok, false);
  assert.equal(Core.normalizeBaseUrl('https://openva.example?token=1').ok, false);
  assert.equal(Core.normalizeBaseUrl('https://openva.example#frag').ok, false);
});

test('normalizeBaseUrl rejects empty and host-less values', () => {
  assert.equal(Core.normalizeBaseUrl('').ok, false);
  assert.equal(Core.normalizeBaseUrl('   ').ok, false);
  assert.equal(Core.normalizeBaseUrl(null).ok, false);
  assert.equal(Core.normalizeBaseUrl('https:///nohost').ok, false);
});

// --------------------------------------------------------------------------- headers

test('normalizeHeader collapses case, spaces, hyphens and underscores', () => {
  assert.equal(Core.normalizeHeader('Vendor Name'), 'vendor_name');
  assert.equal(Core.normalizeHeader('vendor-name'), 'vendor_name');
  assert.equal(Core.normalizeHeader('  vendor__name  '), 'vendor_name');
  assert.equal(Core.normalizeHeader('Company Registration Number'), 'company_registration_number');
  assert.equal(Core.normalizeHeader(''), '');
});

test('resolveInputColumns maps aliases to canonical fields', () => {
  const result = Core.resolveInputColumns(['Supplier', 'Website', 'Legal Name', 'Company Registration Number', 'notes']);
  assert.ok(result.ok);
  assert.deepEqual(result.columns, {
    vendor_name: 0,
    domain: 1,
    business_entity_name: 2,
    registration_number: 3,
  });
});

test('resolveInputColumns rejects ambiguous duplicate headers', () => {
  const result = Core.resolveInputColumns(['Vendor Name', 'vendor_name']);
  assert.equal(result.ok, false);
  assert.match(result.error, /[Aa]mbiguous/);
});

test('resolveInputColumns ignores unrelated columns', () => {
  const result = Core.resolveInputColumns(['vendor', 'spend', 'owner']);
  assert.ok(result.ok);
  assert.deepEqual(result.columns, { vendor_name: 0 });
});

// --------------------------------------------------------------------------- payloads

test('buildVendorPayload contains only supported identity fields and a string row_id', () => {
  const columns = { vendor_name: 0, domain: 1, business_entity_name: 2, registration_number: 3 };
  const vendor = Core.buildVendorPayload(['Stripe', 'stripe.com', '', ''], columns, 12);
  assert.deepEqual(vendor, {
    row_id: '12',
    vendor_name: 'Stripe',
    domain: 'stripe.com',
    business_entity_name: null,
    registration_number: null,
  });
  assert.deepEqual(Object.keys(vendor).sort(), [
    'business_entity_name',
    'domain',
    'registration_number',
    'row_id',
    'vendor_name',
  ]);
});

test('buildVendorPayload serializes numeric cells and uses the sheet row number as row_id', () => {
  const columns = { vendor_name: 0, registration_number: 1 };
  const vendor = Core.buildVendorPayload(['Acme', 12345], columns, 7);
  assert.equal(vendor.row_id, '7'); // row_id is the sheet row number, serialized as a string
  assert.equal(vendor.registration_number, '12345');
});

test('buildVendorPayload returns null for a fully blank row (skipped)', () => {
  const columns = { vendor_name: 0, domain: 1 };
  assert.equal(Core.buildVendorPayload(['', '   '], columns, 5), null);
});

// --------------------------------------------------------------------------- batching

test('chunkRows preserves order and duplicates', () => {
  const items = [];
  for (let i = 1; i <= 250; i++) items.push({ row_id: String(i), vendor_name: i % 2 ? 'Stripe' : 'Slack' });
  const batches = Core.chunkRows(items, 100);
  assert.equal(batches.length, 3);
  assert.deepEqual(batches.map((b) => b.length), [100, 100, 50]);
  const flat = batches.flat();
  assert.deepEqual(flat.map((v) => v.row_id), items.map((v) => v.row_id));
});

test('chunkRows keeps duplicate vendors as independent entries', () => {
  const dup = { row_id: '2', vendor_name: 'Stripe' };
  const batches = Core.chunkRows([{ row_id: '1', vendor_name: 'Stripe' }, dup], 100);
  assert.equal(batches[0].length, 2);
  assert.notEqual(batches[0][0].row_id, batches[0][1].row_id);
});

// --------------------------------------------------------------------------- response validation

function makeResult(rowId, projection) {
  return { row_id: rowId, spreadsheet: projection || { openva_match_status: 'matched' } };
}

function makeBody(rowIds, digest) {
  return {
    snapshot: { snapshot_digest: digest || 'sha256:abc' },
    results: rowIds.map((id) => makeResult(id)),
  };
}

test('validateEnrichmentResponse accepts a correct response', () => {
  const result = Core.validateEnrichmentResponse(makeBody(['1', '2']), ['1', '2']);
  assert.ok(result.ok);
  assert.equal(result.snapshotDigest, 'sha256:abc');
});

test('validateEnrichmentResponse rejects a result-count mismatch', () => {
  const result = Core.validateEnrichmentResponse(makeBody(['1']), ['1', '2']);
  assert.equal(result.ok, false);
});

test('validateEnrichmentResponse rejects a row_id mismatch', () => {
  const result = Core.validateEnrichmentResponse(makeBody(['1', '9']), ['1', '2']);
  assert.equal(result.ok, false);
});

test('validateEnrichmentResponse rejects a missing spreadsheet projection', () => {
  const body = { snapshot: { snapshot_digest: 'sha256:x' }, results: [{ row_id: '1' }] };
  const result = Core.validateEnrichmentResponse(body, ['1']);
  assert.equal(result.ok, false);
});

test('validateEnrichmentResponse rejects a missing snapshot digest', () => {
  const body = { snapshot: {}, results: [makeResult('1')] };
  assert.equal(Core.validateEnrichmentResponse(body, ['1']).ok, false);
  assert.equal(Core.validateEnrichmentResponse(null, ['1']).ok, false);
});

// --------------------------------------------------------------------------- batch merge

test('mergeBatchResponses concatenates batches sharing one snapshot digest', () => {
  const a = { snapshotDigest: 'sha256:x', results: [makeResult('1'), makeResult('2')] };
  const b = { snapshotDigest: 'sha256:x', results: [makeResult('3')] };
  const merged = Core.mergeBatchResponses([a, b]);
  assert.ok(merged.ok);
  assert.deepEqual(merged.results.map((r) => r.row_id), ['1', '2', '3']);
});

test('mergeBatchResponses aborts when the snapshot digest changes between batches', () => {
  const a = { snapshotDigest: 'sha256:x', results: [makeResult('1')] };
  const b = { snapshotDigest: 'sha256:y', results: [makeResult('2')] };
  const merged = Core.mergeBatchResponses([a, b]);
  assert.equal(merged.ok, false);
  assert.match(merged.error, /snapshot changed/i);
});

// --------------------------------------------------------------------------- formula injection

test('safeCellValue neutralizes formula-like values but keeps URLs usable', () => {
  assert.equal(Core.safeCellValue('=SUM(A1:A2)'), "'=SUM(A1:A2)");
  assert.equal(Core.safeCellValue('+1'), "'+1");
  assert.equal(Core.safeCellValue('-1'), "'-1");
  assert.equal(Core.safeCellValue('@handle'), "'@handle");
  assert.equal(Core.safeCellValue('https://openva.example/dpa'), 'https://openva.example/dpa');
  assert.equal(Core.safeCellValue('Stripe'), 'Stripe');
});

test('safeCellValue maps null/undefined to blank cells', () => {
  assert.equal(Core.safeCellValue(null), '');
  assert.equal(Core.safeCellValue(undefined), '');
});

// --------------------------------------------------------------------------- output mapping

test('OPENVA_OUTPUT_COLUMNS is the stable projection in the documented order', () => {
  assert.deepEqual(Core.OPENVA_OUTPUT_COLUMNS, [
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
  ]);
});

test('mapProjectionToOutputRow orders columns and blanks missing values', () => {
  const projection = {
    openva_match_status: 'matched',
    openva_vendor_id: 'stripe',
    openva_vendor_name: 'Stripe',
    openva_dpa: 'https://stripe.com/legal/dpa',
    openva_trust_center: null,
    openva_notes: '',
  };
  const row = Core.mapProjectionToOutputRow(projection, Core.OPENVA_OUTPUT_COLUMNS);
  assert.equal(row.length, Core.OPENVA_OUTPUT_COLUMNS.length);
  assert.equal(row[0], 'matched');
  assert.equal(row[3], 'https://stripe.com/legal/dpa');
  assert.equal(row[7], ''); // openva_trust_center missing -> blank
  assert.equal(row[10], ''); // openva_snapshot_digest absent -> blank, not "undefined"
});

test('mapProjectionToOutputRow escapes a formula-like returned vendor name', () => {
  const row = Core.mapProjectionToOutputRow(
    { openva_match_status: 'matched', openva_vendor_name: '=HYPERLINK("http://evil","x")' },
    Core.OPENVA_OUTPUT_COLUMNS
  );
  assert.equal(row[2], '\'=HYPERLINK("http://evil","x")');
});

// --------------------------------------------------------------------------- column planning

test('planOutputColumns appends new OpenVA columns to the right of existing data', () => {
  const plan = Core.planOutputColumns(['vendor_name', 'domain'], Core.OPENVA_OUTPUT_COLUMNS);
  assert.equal(plan.assignments.openva_match_status, 2);
  assert.equal(plan.totalWidth, 2 + Core.OPENVA_OUTPUT_COLUMNS.length);
  assert.equal(plan.headerWrites.length, Core.OPENVA_OUTPUT_COLUMNS.length);
});

test('planOutputColumns reuses existing OpenVA columns by normalized header', () => {
  const header = ['vendor_name', 'OpenVA Match Status', 'domain'];
  const plan = Core.planOutputColumns(header, Core.OPENVA_OUTPUT_COLUMNS);
  assert.equal(plan.assignments.openva_match_status, 1); // reused, not appended
  assert.ok(plan.headerWrites.every((w) => w.value !== 'openva_match_status'));
});

test('groupContiguous splits indices into ascending runs', () => {
  assert.deepEqual(Core.groupContiguous([2, 3, 4, 5]), [[2, 3, 4, 5]]);
  assert.deepEqual(Core.groupContiguous([1, 2, 4, 5]), [[1, 2], [4, 5]]);
});

// --------------------------------------------------------------------------- retry policy

test('isRetryableStatus retries only transient statuses', () => {
  for (const status of [429, 502, 503, 504]) assert.equal(Core.isRetryableStatus(status), true, String(status));
  for (const status of [400, 401, 404, 413, 422, 200]) assert.equal(Core.isRetryableStatus(status), false, String(status));
});
