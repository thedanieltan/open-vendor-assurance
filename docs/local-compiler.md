# Local CSV Compiler

OpenVA ships a small local CSV compiler for consumers who want structured
compiled vendor information without using the browser UI or operating a resolver
service.

Run it from a repository checkout:

```bash
python -m tools.openva.resolve_csv input.csv \
  --source-types security_or_trust,dpa,subprocessors,privacy_notice,status_page \
  --out-json compiled-vendors.json \
  --out-csv compiled-vendors.csv
```

The compiler reads the input CSV locally, matches vendor rows against the
committed static/community index, and writes:

- compiled vendor information JSON rows;
- a flat CSV that preserves the original input columns exactly and appends only
  the compiled source fields.

Supported input columns:

```text
vendor_name,business_entity_name,domain,jurisdiction,registration_number,registered_address
```

The flat CSV download appends this template:

```text
compiled_vendor_name,compiled_domain,dpa_url,subprocessors_url,privacy_notice_url,security_or_trust_url,status_page_url
```

The compiler is local and does not make network calls, fetch URLs, perform live
verification, discover missing sources, upload files, use accounts, use BYOK, run
a daemon, or call a hosted OpenVA API.

Blank compiled fields mean no compiled value is available for that row and
column. `security_or_trust_url` intentionally collapses trust centers and
security pages because the download is a working sheet for CISO, DPO, and
procurement review, not a source-type audit contract.

The CSV no longer emits row-level `openva_*` fields, `not_advice`, status fields,
reason fields, review-note fields, candidate basis fields, verification basis
fields, or checked-at fields. Those terms are implementation details and do not
belong in the human download template.
