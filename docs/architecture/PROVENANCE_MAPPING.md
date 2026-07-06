# OpenVA Provenance Mapping — Reference Implementation of `public-source`

Status: PROVISIONAL. Operational metadata only. This document is not legal,
compliance, procurement, security, KYC, AML, audit, or vendor-risk advice.

This document maps OpenVA onto the portfolio
[Provenance & Source-Fidelity Vocabulary](./PROVENANCE_VOCABULARY.md)
(`contract_version = "0.1.0"`). OpenVA vendors a pinned copy of that neutral
vocabulary; it does not own it. Changes to the shared contract are versioned
upstream, not here.

## OpenVA is the `public-source` reference implementation

Everything in the OpenVA catalog is **public-source-only by charter**. Every
record is compiled from publicly published, vendor-controlled,
regulator-controlled, or standards-body-controlled sources, accessible without
login, credentials, NDA, sales approval, customer status, or anti-bot bypass
(see `docs/catalog-agent-protocol.md`). OpenVA therefore holds exactly one
portfolio tier:

```text
tier = public-source
```

OpenVA never emits `synthetic`, `sandbox`, `connected`, `authored`, or
`derived` catalog records. There is no path in the catalog by which a record
acquires production-system provenance or human-authored interpretation. This
single-tier posture is what makes OpenVA the reference implementation of
`public-source`: it demonstrates the tier in isolation, with no laundering
surface and no mixed-fidelity records.

## Verification-status is a refinement *within* `public-source`

The portfolio tier is coarse: it states only that a record's source is publicly
published. OpenVA refines that single tier with its own verification-status and
source-reference model. The refinement lives strictly *inside* `public-source`
and never changes the tier.

OpenVA's catalog lifecycle states refine trust within the tier:

```text
candidate → machine_provisional → active
```

with the off-path states:

```text
deferred
rejected
quarantined
rolled_back
```

A record moving from `candidate` to `active`, or being `quarantined` or
`rolled_back`, is a movement in verification confidence about a public source.
It is **not** a movement between portfolio tiers. A `quarantined` OpenVA record
is still `public-source`; it is public-source metadata whose verification is in
doubt, not a different provenance class.

This is intentional and mirrors the vocabulary's own note:

> OpenVA: catalog records → `public-source` (verification-status refines) —
> reference implementation.

## Field mapping

Each OpenVA catalog record maps onto the shared fields as follows:

| Shared field        | OpenVA source                                                        |
|---------------------|----------------------------------------------------------------------|
| `tier`              | Constant `public-source` for every catalog record (by charter).      |
| `source_ref`        | The public source URL / citation recorded on the source reference.   |
| `captured_at`       | Observation / recorded time for the source, where present.           |
| `fidelity_note`     | The verification status (`candidate`, `machine_provisional`, `active`, `deferred`, `rejected`, `quarantined`, `rolled_back`) plus any refinement note. |
| `contract_version`  | `"0.1.0"` (the pinned vocabulary version).                           |

Notes:

- `source_ref` is the public URL or citation only. OpenVA remains
  metadata-only: no raw PDFs, HTML snapshots, screenshots, or extracted full
  text are stored, per the catalog-agent protocol.
- `fidelity_note` carries the verification-status refinement. Consumers reading
  only `tier` see `public-source`; consumers that understand OpenVA can read the
  finer status from `fidelity_note`.
- Because OpenVA is single-tier, the vocabulary's derived-min-fidelity
  (no-laundering) rule is trivially satisfied: there are no cross-tier
  derivations to launder.

## Non-advisory boundary is unchanged

Mapping OpenVA onto the shared vocabulary changes nothing about OpenVA's
non-advisory posture. `public-source` and its verification-status refinements
describe **source facts** — that a vendor publishes a given public page, and how
confidently OpenVA has verified that source. They never assert that a vendor is
compliant, safe, approved, adequate, certified, or low/high risk. The
prohibited advisory wording in `docs/catalog-agent-protocol.md` continues to
govern all catalog records. Provenance tagging is descriptive metadata, not an
endorsement, and confers no OpenVA verification or certification of the vendor.
