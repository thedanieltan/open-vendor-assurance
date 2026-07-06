# OpenVA for Google Sheets

A Google Apps Script integration that enriches vendor rows in a Google Sheet against an
OpenVA catalogue, using the existing OpenVA `/v1/enrich` API.

> **This is a secondary compatibility surface, not the primary distribution path.**
> OpenVA's primary model is agent-composed: a user's existing agent reads the
> workspace through its own connector and calls OpenVA's read-only HTTP/MCP tools
> (see [`docs/agent-workspace-composition.md`](../../docs/agent-workspace-composition.md)
> and [ADR-0005](../../docs/architecture/decisions/ADR-0005-native-clients-as-secondary-compatibility-surfaces.md)).
> This client remains useful as a tested reference and a fallback for environments
> without a capable agent. It is not abandoned, and it reuses the shared enrichment
> contract rather than reproducing any matching or ranking logic.

No local Python, Docker, repository checkout or API secret is required. The current
release requires manual installation into a bound Apps Script project (see "Create a bound
Apps Script project" below). Marketplace or centrally deployed add-on distribution is not
yet available.

> Future objective: a zero-install Google Workspace add-on. That does not exist yet;
> installation is currently manual.

## 1. What it does

From a custom **OpenVA** menu you can:

1. Configure the OpenVA API endpoint.
2. Configure which source types to request.
3. Test the connection.
4. Enrich the selected rows, or the whole active sheet.

For each row it sends the supported vendor-identity fields to `POST /v1/enrich`, receives
canonical public-source references, and writes stable `openva_*` columns back into the
sheet. All matching, source ranking, and canonicality logic stays in the OpenVA service —
this client only consumes the API.

## 2. Boundary: cached-pack, non-advisory

Results are **public-source references cached to the service's loaded catalogue
snapshot**. They are:

- not advice;
- not live verification (no source is fetched or checked during a request);
- not compliance approval;
- not security certification;
- not legal advice;
- not a vendor-risk judgement.

An **unmatched** vendor means *no catalogue match was found in the loaded snapshot* — it
does **not** mean the vendor is unsafe, non-compliant, or lacks a DPA. A missing canonical
source means OpenVA does not currently have that canonical source in the loaded snapshot.

## 3. Required sheet headers

Row 1 must be the header row. At least one of these identity fields must have a value for a
row to be sent:

| Canonical field        | Meaning                          |
| ---------------------- | -------------------------------- |
| `vendor_name`          | Common vendor / supplier name    |
| `domain`               | Primary vendor domain            |
| `business_entity_name` | Registered legal entity name     |
| `registration_number`  | Company registration number      |

## 4. Supported header aliases

Headers are matched case-insensitively, with whitespace, hyphens, and underscores
normalized. Recognized variants:

- **vendor_name:** `vendor_name`, `vendor name`, `vendor`, `supplier`, `supplier_name`, `supplier name`
- **domain:** `domain`, `vendor_domain`, `vendor domain`, `website`, `website domain`
- **business_entity_name:** `business_entity_name`, `business entity name`, `legal_name`, `legal name`
- **registration_number:** `registration_number`, `registration number`, `company_registration_number`, `company registration number`

If two different headers map to the same canonical field (e.g. `Vendor Name` and
`vendor_name`), the integration stops and asks you to rename one column rather than
silently guessing.

## 5. Output columns

The API's stable `spreadsheet` projection is written back, in this order:

```
openva_match_status
openva_vendor_id
openva_vendor_name
openva_dpa
openva_subprocessors
openva_privacy_notice
openva_security
openva_trust_center
openva_compliance
openva_last_observed_at
openva_snapshot_digest
openva_notes
```

Existing OpenVA columns are reused (matched by normalized header); missing ones are
appended to the right of your data. Only processed rows are written: skipped and unselected
rows are excluded from every write range, so a formula in a skipped row between two
processed rows is left in place. Non-OpenVA columns are not overwritten, deleted, or
reordered, and rows are not deleted, reordered, or deduplicated. Missing values are written
as blank cells.

## 6. Configure the API endpoint

**OpenVA → Configure API endpoint.** Enter the HTTPS base URL of an OpenVA deployment,
for example `https://openva.example`. The value is normalized and validated:

- only an HTTPS origin or HTTPS base path is accepted;
- embedded credentials, fragments, and query strings are rejected;
- non-HTTPS and `javascript:` / `data:` schemes are rejected;
- a trailing slash is removed.

The endpoint is stored in this document's properties
(`PropertiesService.getDocumentProperties()`, key `OPENVA_API_BASE_URL`). It is a public
service URL, not a secret. There is no hardcoded production endpoint — you must configure
one before enriching.

## 6a. Configure source types (optional)

**OpenVA → Configure source types** opens a checkbox dialog for choosing which canonical
source types to request from `/v1/enrich`:

```
dpa
subprocessors_list
privacy_notice
security_page
trust_center
compliance_page
```

The selection is stored in this document's properties (key `OPENVA_SOURCE_TYPES`,
non-sensitive). When nothing is saved, all supported types are requested. At least one type
must be selected; unknown values are rejected; the saved order is always the canonical
order above. The relevant output columns for unselected types are left blank.

## 7. Requires a public-read OpenVA deployment

This client carries **no API key**. It targets an OpenVA deployment configured with
`OPENVA_PUBLIC_READ_ENABLED=true`. If the service returns `401`, you will see:

> This OpenVA endpoint does not permit public read access. Ask the service administrator to
> enable the read-only public API or provide an approved intermediary.

## 8. Test the connection

**OpenVA → Test API connection** calls `GET /v1/catalog/meta` and shows the profile id,
vendor count, source count, and snapshot digest. This is a metadata read, not live source
verification.

## 9. Enrich selected rows

Select a contiguous range and choose **OpenVA → Enrich selected rows**. Every selected row
number (excluding the header) is processed; you do not need to select the input columns
themselves.

## 10. Enrich the active sheet

**OpenVA → Enrich active sheet** processes rows 2 through the last data row. Rows whose
supported identity fields are all blank are skipped.

## 11. What data is transmitted

For each processed row, only the supported identity fields and a `row_id` (the sheet row
number, as a string) are sent:

```json
{
  "vendors": [
    { "row_id": "12", "vendor_name": "Stripe", "domain": "stripe.com",
      "business_entity_name": null, "registration_number": null }
  ],
  "source_types": ["dpa", "subprocessors_list", "privacy_notice",
                   "security_page", "trust_center", "compliance_page"]
}
```

The `source_types` list reflects your saved selection (all supported types by default). The
integration never sends the whole spreadsheet, unrelated columns, formulas, notes, hidden
metadata, sheet names, spreadsheet ids, or your email address.

Rows are sent in sheet order, in bounded batches of 100. All batch responses are validated
(result count, order, `row_id` correspondence, spreadsheet projection, and a single shared
snapshot digest) before anything is written. If a batch fails, or the catalogue snapshot
changes mid-run, the operation aborts and writes nothing.

## 12. What is not persisted

Vendor identities are never stored outside the spreadsheet — not in `PropertiesService`,
`CacheService`, logs, script settings, hidden sheets, or external analytics. Request
payloads and full API responses are never logged. Only the configured endpoint URL (not
vendor data) is stored, in document properties.

## 13. Google authorization scopes

`appsscript.json` requests the minimum scopes:

- `https://www.googleapis.com/auth/spreadsheets.currentonly` — read/write the current
  spreadsheet only;
- `https://www.googleapis.com/auth/script.external_request` — HTTPS requests to the
  configured OpenVA API;
- `https://www.googleapis.com/auth/script.container.ui` — the custom menu and dialogs.

No Gmail, Drive-wide, Contacts, Calendar, profile, or admin scopes are requested.

## 14. Create a bound Apps Script project

1. Open your Google Sheet.
2. **Extensions → Apps Script.**
3. Set the project to the **V8** runtime (default for new projects).
4. Create files matching `src/` and paste in the contents. The complete set is required:
   - `Core.gs`
   - `ApiClient.gs`
   - `SheetAdapter.gs`
   - `Menu.gs`
   - `Help.html` (the **Help** dialog)
   - `SourceTypes.html` (the **Configure source types** dialog)

   The `module.exports` block at the bottom of `Core.gs` is inert in Apps Script — leave it
   in place.
5. Replace the manifest with `appsscript.json` (enable "Show appsscript.json" under Project
   Settings).
6. Reload the spreadsheet; the **OpenVA** menu appears.

## 15. Optional `clasp` workflow

If you prefer local development with
[`clasp`](https://github.com/google/clasp), copy `.clasp.example.json` to `.clasp.json` and
insert *your own* script id. `.clasp.json` is git-ignored — never commit a real script id.

```bash
cp .clasp.example.json .clasp.json   # then edit scriptId
clasp push
```

## 16. Current limitations

- Manual installation only. You create a bound Apps Script project and paste in the files;
  there is no one-click install. A zero-install Google Workspace add-on is a future
  objective, not a current capability.
- Google Sheets only. There is no Excel or Word client here, and this is not published in
  the Google Workspace Marketplace.
- No hosted public OpenVA endpoint is bundled; you configure your own.
- A single enrichment run uses one catalogue snapshot; if the snapshot changes during a
  multi-batch run, the run aborts and asks you to rerun.
- One enrichment runs at a time per spreadsheet. A document lock is held across reads, API
  calls, and writes; a second run started while one is in progress is asked to wait.
- Duplicate input headers and duplicate OpenVA output columns fail closed before any API
  call, so you are asked to rename the conflicting column rather than risk a wrong write.
- Enrichment is an explicit menu action only — there are no per-cell network functions, no
  `onEdit` calls, and no scheduled triggers.

## 17. Troubleshooting

| Symptom                          | Cause / action                                                                 |
| -------------------------------- | ------------------------------------------------------------------------------ |
| "No API endpoint configured"     | Run **Configure API endpoint** with an HTTPS URL.                              |
| `401`                            | The deployment does not allow public read; ask the administrator to enable it. |
| `413`                            | Request too large; reduce the number of rows (batches are already 100).        |
| `422`                            | The service rejected the input; check the identity columns.                    |
| Timeout / "Could not reach…"     | Check the endpoint URL and network; transient errors are retried twice.        |
| "The catalogue snapshot changed" | The catalogue moved mid-run; rerun the enrichment.                             |
| "Ambiguous headers"              | Two input columns map to the same identity field; rename one.                  |
| "Ambiguous OpenVA output columns"| Two columns map to the same `openva_*` output; rename or remove the duplicate. |
| "Another OpenVA enrichment is already running" | Wait for the in-progress run to finish, then retry.              |

## Development

Pure transformation logic lives in `src/Core.gs` and is tested with Node's built-in runner
(no third-party framework, no runtime dependencies):

```bash
node --test integrations/google-sheets/test/*.test.mjs
```

The repository also runs these via `tests/test_google_sheets_integration.py`, which adds
static contract checks (V8 runtime, minimal scopes, no embedded key, only `/v1/catalog/meta`
and `/v1/enrich` called).

## CI routing smoke

This README is the narrowest Google Sheets surface used for routing validation. A docs-only
edit here should run the Google Sheets integration lane and skip unrelated catalog, MCP, and
release-site lanes.
