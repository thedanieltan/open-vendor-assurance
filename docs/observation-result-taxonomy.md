# Observation Result Taxonomy

OpenVA observations are public-source fetch attempts. They are not evidence of vendor compliance, security posture, contractual sufficiency, or procurement suitability.

The observer records only what happened during a bounded, transparent, metadata-only fetch attempt.

## Principles

- Public sources only.
- No credentials, login, portal access, CAPTCHA bypass, form submission, or anti-bot workaround.
- No raw document storage by default.
- No hashing of partial, blocked, unsafe, or failed responses.
- Ambiguous results are not written by default.
- Human review is required before treating ambiguous results as durable observation history.

## Result categories

### `ok`

The source was fetched successfully.

OpenVA may compute:

- `raw_sha256`
- `normalized_text_sha256`

OpenVA still does not store the raw document.

Write behavior:

```text
written by default
```

### `not_modified`

The source was not modified according to conditional request metadata.

This result is reserved for future conditional-fetch support.

Write behavior:

```text
written by default once implemented
```

### `moved`

The source appears to have moved.

This result is reserved for future canonical-source review flows. A redirect can be safe at fetch time but still require maintainer review before OpenVA changes canonical source metadata.

Write behavior:

```text
maintainer review expected
```

### `access_changed`

The source access behavior changed from the catalog expectation.

Examples:

- a previously public source starts requiring login;
- a public document becomes unavailable;
- an access pattern no longer matches the source record.

Write behavior:

```text
maintainer review expected
```

### `bot_protected`

The source may still be public to humans, but OpenVA's transparent observer encountered bot protection, access controls, or challenge-like content.

Examples:

- HTTP 401, 403, 407, or 429;
- CAPTCHA or human-verification page;
- browser-check page;
- customer/trust-portal challenge page.

OpenVA does not bypass these controls and does not compute hashes for this result.

This result does not invalidate the underlying source record by itself. It means OpenVA automation could not fetch the source transparently at that time. Removing, deprecating, or downgrading source metadata requires separate public evidence or maintainer review.

Write behavior:

```text
skipped by default unless --allow-ambiguous-write is passed
```

### `size_limited`

The response exceeded OpenVA's byte limit.

OpenVA does not hash partial oversized responses because a partial hash would create misleading evidence.

Write behavior:

```text
skipped by default unless --allow-ambiguous-write is passed
```

### `fetch_failed`

The fetch failed for a non-classified reason.

Examples:

- timeout;
- DNS failure;
- TLS or transport failure;
- non-bot-protection HTTP failure.

OpenVA does not compute hashes for failed fetches.

Write behavior:

```text
skipped by default unless --allow-ambiguous-write is passed
```

### `quarantined`

The source URL or redirect target failed URL-safety checks.

Examples:

- non-HTTP(S) scheme;
- localhost or loopback target;
- private, link-local, multicast, reserved, or unspecified IP target;
- unsafe redirect.

OpenVA does not trust or hash quarantined fetch output.

Write behavior:

```text
skipped by default unless --allow-ambiguous-write is passed
```

## Ambiguous-result rule

The following results are ambiguous for durable observation history:

```text
bot_protected
size_limited
fetch_failed
quarantined
```

They are useful in dry-run summaries and operational diagnostics, but they are not written by default because they may reflect transient network state, anti-bot behavior, oversized content, or unsafe source behavior.

A maintainer may intentionally write them with:

```bash
python -m tools.openva.observe observe-pilot --allow-ambiguous-write
```

Use that override only when the result itself is meaningful history and the maintainer wants the public corpus to record that state.

## Dry-run output

Dry-run output defaults to a compact summary:

```text
OpenVA observation summary
mode: dry-run
sources: 5
ok: 3
bot_protected: 1
size_limited: 1

Results by source:
- example-source: ok (http=200, final_url=https://example.com)
```

Raw observation YAML can be printed after the summary with:

```bash
python -m tools.openva.observe observe-pilot --dry-run --emit-yaml
```

## Non-advisory boundary

Observation results must not be described as:

- compliant;
- approved;
- safe;
- sufficient;
- certified by OpenVA;
- recommended;
- low risk or high risk.

They describe fetch behavior only.
