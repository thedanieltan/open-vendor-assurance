# Local Hint-Only CSV Compiler

OpenVA ships a small local CSV compiler for consumers who want resolver
result-pack output without using the browser UI or operating a resolver service.

Run it from a repository checkout:

```bash
python -m tools.openva.resolve_csv input.csv \
  --source-types trust_center,dpa,subprocessors_list,privacy_notice,security_page,status_page \
  --out-json result-pack.json \
  --out-csv result-pack.csv
```

The compiler reads the input CSV locally, matches vendor rows against the
committed OpenVA static/community index, and writes:

- resolver result-pack JSON rows;
- a flat CSV that preserves the original input columns and appends deterministic
  `openva_*` columns.

Supported input columns:

```text
vendor_name,business_entity_name,domain,jurisdiction,registration_number,registered_address
```

The compiler is v0.1 and hint-only. It does not make network calls, fetch URLs,
perform live verification, discover missing sources, upload files, use accounts,
use BYOK, run a daemon, or call a hosted OpenVA API.

Candidate source URLs from the committed index are emitted only as candidate
locators:

```text
status=not_checked
candidate_basis=cached_locator
verification_basis=not_checked
checked_at=null
```

When no candidate source URL exists for a requested source type, the compiler
emits:

```text
status=not_checked
candidate_basis=none
verification_basis=not_checked
checked_at=null
```

The compiler never emits `verification_basis=verified_live`,
`verification_basis=live_unavailable`, `verification_basis=live_gated`,
`verification_basis=live_not_found`, or source `status=found`. Verified outcomes
require separate consumer-side live verification through a consumer-side live
resolver run. The community index is hint-only and is not authoritative evidence.

All output keeps `not_advice=true`. OpenVA results are not legal, compliance,
procurement, audit, security, KYC, AML, sanctions, regulatory, vendor-risk, or
other professional advice.
