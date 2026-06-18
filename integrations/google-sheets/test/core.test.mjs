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

test('planOutputColumns appends new OpenVA columns when none exist', () => {
  const plan = Core.planOutputColumns(['vendor_name', 'domain'], Core.OPENVA_OUTPUT_COLUMNS);
  assert.ok(plan.ok);
  assert.equal(plan.assignments.openva_match_status, 2);
  assert.equal(plan.totalWidth, 2 + Core.OPENVA_OUTPUT_COLUMNS.length);
  assert.equal(plan.headerWrites.length, Core.OPENVA_OUTPUT_COLUMNS.length);
});

test('planOutputColumns reuses a single existing OpenVA column by normalized header', () => {
  const header = ['vendor_name', 'OpenVA Match Status', 'domain'];
  const plan = Core.planOutputColumns(header, Core.OPENVA_OUTPUT_COLUMNS);
  assert.ok(plan.ok);
  assert.equal(plan.assignments.openva_match_status, 1); // reused, not appended
  assert.ok(plan.headerWrites.every((w) => w.value !== 'openva_match_status'));
});

test('planOutputColumns rejects duplicate exact output headers', () => {
  const header = ['vendor_name', 'openva_dpa', 'openva_dpa'];
  const plan = Core.planOutputColumns(header, Core.OPENVA_OUTPUT_COLUMNS);
  assert.equal(plan.ok, false);
  assert.match(plan.error, /Ambiguous OpenVA output columns.*openva_dpa/);
});

test('planOutputColumns rejects duplicate normalized output-header variants', () => {
  const header = ['vendor_name', 'OpenVA DPA', 'openva_dpa'];
  const plan = Core.planOutputColumns(header, Core.OPENVA_OUTPUT_COLUMNS);
  assert.equal(plan.ok, false);
  assert.match(plan.error, /openva_dpa/);
});

test('groupContiguous splits indices into ascending runs', () => {
  assert.deepEqual(Core.groupContiguous([2, 3, 4, 5]), [[2, 3, 4, 5]]);
  assert.deepEqual(Core.groupContiguous([1, 2, 4, 5]), [[1, 2], [4, 5]]);
});

// --------------------------------------------------------------------------- row-run grouping

test('groupContiguousRows returns no runs for empty input', () => {
  assert.deepEqual(Core.groupContiguousRows([]), []);
});

test('groupContiguousRows wraps a single row', () => {
  assert.deepEqual(Core.groupContiguousRows([5]), [[5]]);
});

test('groupContiguousRows keeps one contiguous block as a single run', () => {
  assert.deepEqual(Core.groupContiguousRows([2, 3, 4]), [[2, 3, 4]]);
});

test('groupContiguousRows splits non-contiguous rows', () => {
  assert.deepEqual(Core.groupContiguousRows([2, 3, 5, 8, 9]), [[2, 3], [5], [8, 9]]);
});

test('groupContiguousRows sorts unordered input (ascending contract)', () => {
  assert.deepEqual(Core.groupContiguousRows([9, 2, 8, 3, 5]), [[2, 3], [5], [8, 9]]);
});

test('groupContiguousRows deduplicates repeated row numbers', () => {
  assert.deepEqual(Core.groupContiguousRows([2, 2, 3, 3, 3, 5]), [[2, 3], [5]]);
});

// --------------------------------------------------------------------------- write operations

// Header that already carries vendor_name + domain, no OpenVA columns yet.
const PLAIN_HEADER = ['vendor_name', 'domain'];

function projection(values) {
  return Object.assign({ openva_match_status: 'matched' }, values);
}

test('buildCellWriteOperations writes exact processed rows only, skipping gaps', () => {
  const plan = Core.planOutputColumns(PLAIN_HEADER, Core.OPENVA_OUTPUT_COLUMNS);
  const ops = Core.buildCellWriteOperations(plan, [2, 4], {
    2: projection({ openva_vendor_id: 'stripe' }),
    4: projection({ openva_vendor_id: 'slack' }),
  });
  // Two non-contiguous rows -> two single-row operations; none covers row 3.
  assert.equal(ops.length, 2);
  assert.deepEqual(ops.map((o) => o.startRow), [2, 4]);
  for (const op of ops) {
    assert.equal(op.values.length, 1); // exactly one row each
    const lastRow = op.startRow + op.values.length - 1;
    assert.ok(!(op.startRow <= 3 && 3 <= lastRow), 'no operation may span row 3');
  }
});

test('buildCellWriteOperations combines contiguous rows into one run', () => {
  const plan = Core.planOutputColumns(PLAIN_HEADER, Core.OPENVA_OUTPUT_COLUMNS);
  const ops = Core.buildCellWriteOperations(plan, [2, 3, 4], {
    2: projection({}),
    3: projection({}),
    4: projection({}),
  });
  assert.equal(ops.length, 1);
  assert.equal(ops[0].startRow, 2);
  assert.equal(ops[0].values.length, 3);
});

test('buildCellWriteOperations appends columns contiguously to the right of data', () => {
  const plan = Core.planOutputColumns(PLAIN_HEADER, Core.OPENVA_OUTPUT_COLUMNS);
  const ops = Core.buildCellWriteOperations(plan, [2], { 2: projection({ openva_vendor_id: 'stripe' }) });
  assert.equal(ops.length, 1); // all 12 columns contiguous -> one column run
  assert.equal(ops[0].startColumn, 2); // appended after vendor_name(0), domain(1)
  assert.equal(ops[0].values[0].length, Core.OPENVA_OUTPUT_COLUMNS.length);
  assert.equal(ops[0].values[0][0], 'matched'); // openva_match_status
});

test('buildCellWriteOperations maps scattered existing OpenVA columns correctly', () => {
  // openva_dpa already exists at column index 1 (between vendor_name and domain); the rest
  // are appended to the right, producing two column runs.
  const header = ['vendor_name', 'openva_dpa', 'domain'];
  const plan = Core.planOutputColumns(header, Core.OPENVA_OUTPUT_COLUMNS);
  const ops = Core.buildCellWriteOperations(plan, [2], {
    2: projection({ openva_dpa: 'https://stripe.com/dpa', openva_vendor_id: 'stripe' }),
  });
  // The dpa value must land in its existing column (index 1), not in the appended block.
  const dpaOp = ops.find((o) => o.startColumn === 1);
  assert.ok(dpaOp, 'expected a write at the existing openva_dpa column');
  assert.equal(dpaOp.values[0][0], 'https://stripe.com/dpa');
  // The appended run carries openva_match_status as its first column.
  const appended = ops.find((o) => o.startColumn === header.length);
  assert.ok(appended);
  assert.equal(appended.values[0][0], 'matched');
});

test('buildCellWriteOperations leaves missing values blank, not "null"/"undefined"', () => {
  const plan = Core.planOutputColumns(PLAIN_HEADER, Core.OPENVA_OUTPUT_COLUMNS);
  const ops = Core.buildCellWriteOperations(plan, [2], { 2: { openva_match_status: 'no_match' } });
  const row = ops[0].values[0];
  // openva_vendor_id (index 1) absent in projection -> blank cell.
  assert.equal(row[1], '');
  assert.ok(!row.includes('null'));
  assert.ok(!row.includes('undefined'));
});

test('buildCellWriteOperations applies formula-injection protection to written values', () => {
  const plan = Core.planOutputColumns(PLAIN_HEADER, Core.OPENVA_OUTPUT_COLUMNS);
  const ops = Core.buildCellWriteOperations(plan, [2], {
    2: projection({ openva_vendor_name: '=DANGER()' }),
  });
  const nameIndex = Core.OPENVA_OUTPUT_COLUMNS.indexOf('openva_vendor_name');
  assert.equal(ops[0].values[0][nameIndex], "'=DANGER()");
});

test('buildCellWriteOperations returns nothing when there are no processed rows', () => {
  const plan = Core.planOutputColumns(PLAIN_HEADER, Core.OPENVA_OUTPUT_COLUMNS);
  assert.deepEqual(Core.buildCellWriteOperations(plan, [], {}), []);
});

// --------------------------------------------------------------------------- retry policy

test('isRetryableStatus retries only transient statuses', () => {
  for (const status of [429, 502, 503, 504]) assert.equal(Core.isRetryableStatus(status), true, String(status));
  for (const status of [400, 401, 404, 413, 422, 200]) assert.equal(Core.isRetryableStatus(status), false, String(status));
});

// --------------------------------------------------------------------------- source types

test('OPENVA_SUPPORTED_SOURCE_TYPES is the exact canonical API vocabulary', () => {
  assert.deepEqual(Core.OPENVA_SUPPORTED_SOURCE_TYPES, [
    'dpa',
    'subprocessors_list',
    'privacy_notice',
    'security_page',
    'trust_center',
    'compliance_page',
  ]);
});

test('resolveStoredSourceTypes defaults to all supported types when unset', () => {
  assert.deepEqual(Core.resolveStoredSourceTypes(null), Core.OPENVA_SUPPORTED_SOURCE_TYPES);
  assert.deepEqual(Core.resolveStoredSourceTypes(''), Core.OPENVA_SUPPORTED_SOURCE_TYPES);
  assert.deepEqual(Core.resolveStoredSourceTypes('not json'), Core.OPENVA_SUPPORTED_SOURCE_TYPES);
});

test('resolveStoredSourceTypes returns a saved valid selection', () => {
  assert.deepEqual(Core.resolveStoredSourceTypes('["dpa","trust_center"]'), ['dpa', 'trust_center']);
});

test('normalizeSourceTypes returns the fixed canonical order regardless of input order', () => {
  const result = Core.normalizeSourceTypes(['trust_center', 'dpa', 'privacy_notice']);
  assert.ok(result.ok);
  assert.deepEqual(result.sourceTypes, ['dpa', 'privacy_notice', 'trust_center']);
});

test('normalizeSourceTypes dedupes and trims/lowercases', () => {
  const result = Core.normalizeSourceTypes(['DPA', ' dpa ', 'security_page']);
  assert.ok(result.ok);
  assert.deepEqual(result.sourceTypes, ['dpa', 'security_page']);
});

test('normalizeSourceTypes rejects unknown values', () => {
  const result = Core.normalizeSourceTypes(['dpa', 'made_up_type']);
  assert.equal(result.ok, false);
  assert.match(result.error, /made_up_type/);
});

test('normalizeSourceTypes rejects an empty selection', () => {
  assert.equal(Core.normalizeSourceTypes([]).ok, false);
  assert.equal(Core.normalizeSourceTypes(['  ']).ok, false);
});

// --------------------------------------------------------------------------- document lock

function fakeLock() {
  return { locked: false, acquired: 0, released: 0 };
}

test('withDocumentLock does not run the body when the lock cannot be acquired', () => {
  const lock = fakeLock();
  let bodyCalls = 0;
  const result = Core.withDocumentLock(
    {
      acquireLock: () => false,
      releaseLock: () => {
        lock.released += 1;
      },
    },
    () => {
      bodyCalls += 1;
      return { ok: true };
    }
  );
  assert.equal(bodyCalls, 0); // no API call / no write planning happens
  assert.equal(lock.released, 0); // nothing to release
  assert.equal(result.ok, false);
  assert.match(result.error, /already running/i);
});

test('withDocumentLock releases the lock after a successful body', () => {
  const lock = fakeLock();
  const result = Core.withDocumentLock(
    {
      acquireLock: () => {
        lock.acquired += 1;
        return true;
      },
      releaseLock: () => {
        lock.released += 1;
      },
    },
    () => ({ ok: true, enriched: 3 })
  );
  assert.deepEqual(result, { ok: true, enriched: 3 });
  assert.equal(lock.acquired, 1);
  assert.equal(lock.released, 1);
});

test('withDocumentLock releases the lock even when the body throws', () => {
  const lock = fakeLock();
  assert.throws(
    () =>
      Core.withDocumentLock(
        {
          acquireLock: () => true,
          releaseLock: () => {
            lock.released += 1;
          },
        },
        () => {
          throw new Error('boom');
        }
      ),
    /boom/
  );
  assert.equal(lock.released, 1);
});

test('withDocumentLock serializes writers: a second run is rejected while one holds the lock', () => {
  // A shared lock that only one holder can take at a time.
  const shared = { held: false };
  const ports = {
    acquireLock: () => {
      if (shared.held) return false;
      shared.held = true;
      return true;
    },
    releaseLock: () => {
      shared.held = false;
    },
  };
  let writes = 0;
  // First holder runs an inner second attempt before releasing; the second must not write.
  const outer = Core.withDocumentLock(ports, () => {
    const inner = Core.withDocumentLock(ports, () => {
      writes += 1; // would be a concurrent write
      return { ok: true };
    });
    assert.equal(inner.ok, false); // blocked while the outer run holds the lock
    writes += 1;
    return { ok: true };
  });
  assert.ok(outer.ok);
  assert.equal(writes, 1); // only the lock holder wrote
  assert.equal(shared.held, false); // released
});
