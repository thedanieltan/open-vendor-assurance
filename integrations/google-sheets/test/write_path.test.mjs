/**
 * Write-path contract tests for SheetAdapter.gs `writeResults`.
 *
 * Core.gs and SheetAdapter.gs are Apps Script files that share globals rather than module
 * imports. To exercise `writeResults` against a fake sheet, both files are evaluated in one
 * shared VM context (the same way Apps Script exposes top-level functions as globals). A
 * fake sheet records every getRange/getValues/setValues/setValue call so the tests can
 * assert the exact ranges written and prove existing cells are never read.
 *
 *   node --test integrations/google-sheets/test/*.test.mjs
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const srcDir = path.join(here, '..', 'src');

function loadSandbox() {
  const core = fs.readFileSync(path.join(srcDir, 'Core.gs'), 'utf8');
  const adapter = fs.readFileSync(path.join(srcDir, 'SheetAdapter.gs'), 'utf8');
  const sandbox = {};
  vm.createContext(sandbox);
  // Apps Script has no `module`; leaving it undefined keeps Core.gs's export block inert,
  // so its top-level functions become globals on the context (as in Apps Script).
  vm.runInContext(core + '\n' + adapter, sandbox);
  return sandbox;
}

function fakeSheet() {
  const calls = { getValues: 0, setValues: [], setValue: [] };
  const sheet = {
    getRange(row, column, numRows, numColumns) {
      return {
        getValues() {
          calls.getValues += 1;
          const rows = numRows || 1;
          const cols = numColumns || 1;
          return Array.from({ length: rows }, () => Array.from({ length: cols }, () => ''));
        },
        setValues(values) {
          calls.setValues.push({ row, column, numRows, numColumns, values });
        },
        setValue(value) {
          calls.setValue.push({ row, column, value });
        },
      };
    },
  };
  return { sheet, calls };
}

const OUTPUT = [
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

function projection(values) {
  return Object.assign({ openva_match_status: 'matched' }, values);
}

test('writeResults never reads existing cells (no getValues)', () => {
  const sandbox = loadSandbox();
  const plan = sandbox.planOutputColumns(['vendor_name', 'domain'], OUTPUT);
  const { sheet, calls } = fakeSheet();
  sandbox.writeResults(sheet, plan, [2, 4], {
    2: projection({ openva_vendor_id: 'stripe' }),
    4: projection({ openva_vendor_id: 'slack' }),
  });
  assert.equal(calls.getValues, 0);
});

test('writeResults for rows [2, 4] never writes a range covering row 3', () => {
  const sandbox = loadSandbox();
  const plan = sandbox.planOutputColumns(['vendor_name', 'domain'], OUTPUT);
  const { sheet, calls } = fakeSheet();
  sandbox.writeResults(sheet, plan, [2, 4], {
    2: projection({}),
    4: projection({}),
  });
  // Two single-row writes, at rows 2 and 4; neither spans row 3.
  assert.deepEqual(calls.setValues.map((c) => c.row).sort(), [2, 4]);
  for (const call of calls.setValues) {
    assert.equal(call.numRows, 1);
    const lastRow = call.row + call.numRows - 1;
    assert.ok(!(call.row <= 3 && 3 <= lastRow), 'a write covered row 3');
  }
});

test('writeResults combines contiguous rows into a single setValues', () => {
  const sandbox = loadSandbox();
  const plan = sandbox.planOutputColumns(['vendor_name', 'domain'], OUTPUT);
  const { sheet, calls } = fakeSheet();
  sandbox.writeResults(sheet, plan, [2, 3, 4], {
    2: projection({}),
    3: projection({}),
    4: projection({}),
  });
  assert.equal(calls.setValues.length, 1);
  assert.equal(calls.setValues[0].row, 2);
  assert.equal(calls.setValues[0].numRows, 3);
});

test('writeResults creates missing OpenVA headers and writes appended values', () => {
  const sandbox = loadSandbox();
  const plan = sandbox.planOutputColumns(['vendor_name', 'domain'], OUTPUT);
  const { sheet, calls } = fakeSheet();
  sandbox.writeResults(sheet, plan, [2], { 2: projection({ openva_vendor_id: 'stripe' }) });
  // 12 new header cells written at row 1, columns 3..14 (1-based).
  assert.equal(calls.setValue.length, OUTPUT.length);
  assert.deepEqual(calls.setValue.map((c) => c.row), Array(OUTPUT.length).fill(1));
  assert.equal(calls.setValue[0].column, 3);
  // One contiguous value block starting at column 3.
  assert.equal(calls.setValues.length, 1);
  assert.equal(calls.setValues[0].column, 3);
  assert.equal(calls.setValues[0].values[0][0], 'matched');
});

test('writeResults maps a scattered existing OpenVA column to its own range', () => {
  const sandbox = loadSandbox();
  // openva_dpa pre-exists at column index 1 (1-based column 2).
  const plan = sandbox.planOutputColumns(['vendor_name', 'openva_dpa', 'domain'], OUTPUT);
  const { sheet, calls } = fakeSheet();
  sandbox.writeResults(sheet, plan, [2], {
    2: projection({ openva_dpa: 'https://stripe.com/dpa', openva_vendor_id: 'stripe' }),
  });
  const dpaWrite = calls.setValues.find((c) => c.column === 2);
  assert.ok(dpaWrite, 'expected a write at the existing openva_dpa column');
  assert.equal(dpaWrite.values[0][0], 'https://stripe.com/dpa');
});
