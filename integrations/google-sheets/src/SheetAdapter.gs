/**
 * OpenVA for Google Sheets — spreadsheet read/write adapter and enrichment orchestration.
 *
 * This file is the only place that reads from or writes to the spreadsheet. It transmits
 * only the supported vendor-identity fields (via Core helpers) and writes back the stable
 * OpenVA output columns. It never deletes, reorders, or deduplicates user rows or
 * columns, and it never persists vendor identities anywhere.
 */

/** Row 1 is the header row. Returns the header cells, or [] when the sheet is empty. */
function readHeaderRow(sheet) {
  var lastColumn = sheet.getLastColumn();
  if (lastColumn < 1) {
    return [];
  }
  return sheet.getRange(1, 1, 1, lastColumn).getValues()[0];
}

/** Sheet-row numbers in the active contiguous selection, excluding the header row. */
function selectedRowNumbers(sheet) {
  var range = sheet.getActiveRange();
  if (!range) {
    return [];
  }
  var start = Math.max(range.getRow(), 2);
  var end = range.getRow() + range.getNumRows() - 1;
  var rows = [];
  for (var r = start; r <= end; r++) {
    rows.push(r);
  }
  return rows;
}

/** All data rows (2 .. last data row) of the active sheet. */
function activeSheetRowNumbers(sheet) {
  var last = sheet.getLastRow();
  var rows = [];
  for (var r = 2; r <= last; r++) {
    rows.push(r);
  }
  return rows;
}

/**
 * Orchestrate enrichment for an explicit, ordered list of sheet-row numbers.
 *
 * A per-document lock is held across header reads, output-column planning, API calls, and
 * writes, so two concurrent runs can neither create duplicate columns nor overwrite each
 * other. If the lock cannot be acquired, no API call or write occurs.
 *
 * @returns {{ok: true, enriched: number, skipped: number, snapshotDigest: string}
 *           | {ok: false, error: string}}
 */
function enrichRows(rowNumbers) {
  var lock = LockService.getDocumentLock();
  return withDocumentLock(
    {
      acquireLock: function () {
        return lock.tryLock(OPENVA_LOCK_TIMEOUT_MS);
      },
      releaseLock: function () {
        lock.releaseLock();
      },
    },
    function () {
      return enrichRowsLocked(rowNumbers);
    }
  );
}

/**
 * The locked body of enrichRows. Validates configuration, input columns, and the output
 * column plan (failing closed on duplicate output headers) BEFORE any API call. Validates
 * all batch responses (count, order, row_id correspondence, snapshot-digest consistency)
 * before any sheet mutation; on any failure it aborts and writes nothing.
 */
function enrichRowsLocked(rowNumbers) {
  var base = getConfiguredBaseUrl();
  if (!base.ok) {
    return { ok: false, error: base.error + ' Use OpenVA → Configure API endpoint.' };
  }
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var header = readHeaderRow(sheet);
  if (header.length === 0) {
    return { ok: false, error: 'The sheet has no header row. Row 1 must contain column headers.' };
  }
  var resolved = resolveInputColumns(header);
  if (!resolved.ok) {
    return { ok: false, error: resolved.error };
  }
  if (Object.keys(resolved.columns).length === 0) {
    return {
      ok: false,
      error:
        'No supported vendor-identity columns were found. Add at least one of: ' +
        OPENVA_IDENTITY_FIELDS.join(', ') + '.',
    };
  }

  // Plan output columns now, before any API call, so duplicate OpenVA output headers fail
  // closed without sending vendor data or mutating the sheet.
  var plan = planOutputColumns(header, OPENVA_OUTPUT_COLUMNS);
  if (!plan.ok) {
    return { ok: false, error: plan.error };
  }

  var sourceTypes = resolveStoredSourceTypes(
    PropertiesService.getDocumentProperties().getProperty(OPENVA_SOURCE_TYPES_KEY)
  );

  // One bounded read of the cells we need, then build payloads in sheet order.
  var lastColumn = sheet.getLastColumn();
  var processedRows = [];
  var vendors = [];
  var skipped = 0;
  var sorted = rowNumbers.slice().sort(function (a, b) {
    return a - b;
  });
  if (sorted.length > 0) {
    var minRow = sorted[0];
    var maxRow = sorted[sorted.length - 1];
    var block = sheet.getRange(minRow, 1, maxRow - minRow + 1, lastColumn).getValues();
    for (var i = 0; i < sorted.length; i++) {
      var rowNumber = sorted[i];
      var rowValues = block[rowNumber - minRow];
      var vendor = buildVendorPayload(rowValues, resolved.columns, rowNumber);
      if (vendor === null) {
        skipped += 1;
        continue;
      }
      processedRows.push(rowNumber);
      vendors.push(vendor);
    }
  }

  if (vendors.length === 0) {
    return { ok: true, enriched: 0, skipped: skipped, snapshotDigest: '' };
  }

  // Sequential bounded batches. Collect and validate every response before writing.
  var batches = chunkRows(vendors, OPENVA_BATCH_SIZE);
  var validatedBatches = [];
  for (var b = 0; b < batches.length; b++) {
    var batchResult = enrichBatch(base.url, batches[b], sourceTypes);
    if (!batchResult.ok) {
      return { ok: false, error: batchResult.error };
    }
    validatedBatches.push(batchResult);
  }

  var merged = mergeBatchResponses(validatedBatches);
  if (!merged.ok) {
    return { ok: false, error: merged.error };
  }

  var projectionByRow = {};
  for (var m = 0; m < merged.results.length; m++) {
    var result = merged.results[m];
    projectionByRow[String(result.row_id)] = result.spreadsheet;
  }

  writeResults(sheet, plan, processedRows, projectionByRow);

  return {
    ok: true,
    enriched: processedRows.length,
    skipped: skipped,
    snapshotDigest: merged.snapshotDigest,
  };
}

/**
 * Write the OpenVA output columns for the processed rows, using an already-validated
 * column plan (see planOutputColumns).
 *
 * Only processed rows are written. Skipped and unselected rows are excluded from every
 * write range: each write covers one contiguous run of processed rows by one contiguous
 * run of output columns. Existing cells are never read, so a formula in a skipped row
 * between two processed rows is left untouched. Existing OpenVA columns are reused; missing
 * ones are appended to the right.
 */
function writeResults(sheet, plan, processedRows, projectionByRow) {
  plan.headerWrites.forEach(function (write) {
    sheet.getRange(1, write.index + 1).setValue(write.value);
  });
  buildCellWriteOperations(plan, processedRows, projectionByRow).forEach(function (op) {
    sheet
      .getRange(op.startRow, op.startColumn + 1, op.values.length, op.values[0].length)
      .setValues(op.values);
  });
}
