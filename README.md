# open-vendor-assurance

A public, metadata-first system of record for vendor-published assurance materials.

OpenVA is intended to be a public vendor assurance knowledge substrate. It records public-source factual metadata about vendor assurance materials such as data processing addenda, subprocessor lists, trust-center pages, privacy notices, security pages, certification references, KYC/AML statements where public, AI/data terms, and related source references.

OpenVA is not a legal, compliance, procurement, audit, security, KYC, AML, or vendor-risk advice product.

## Doctrine

OpenVA is:

- public-source-only;
- metadata-first;
- factual and non-advisory;
- native-language-aware;
- provenance-driven;
- hash-friendly;
- exportable through universal packs;
- usable independently of any one runtime or application.

OpenVA does not:

- mirror raw vendor documents by default;
- include bespoke agreements;
- include authenticated trust-center or customer portal materials;
- include NDA-gated content;
- state that any vendor is compliant, approved, safe, certified, adequate, suitable, or recommended;
- provide tenant-specific risk decisions;
- replace professional, legal, compliance, procurement, audit, security, KYC, AML, or regulatory advice.

## Architecture stance

OpenVA owns the public vendor assurance substrate:

```text
vendor_public_profile
public_source_reference
artifact_reference
subprocessor_reference
source_observation
freshness_status
questionnaire_template
change_event
```

Downstream systems own private operational state:

```text
workspace_vendor
vendor_review
risk_decision
approval
evidence_upload
audit_event
control_mapping
user-specific obligation impact
```

OpenVA should export a universal dataset/pack format. Compliance OS may consume that universal export through a compatibility profile, but OpenVA is not merely a Compliance OS module folder.

## Public-source-only rule

If a source requires login, NDA, customer status, sales approval, support ticket access, private portal access, credentialed access, or anti-bot bypass, it is out of scope.

The repository may record that a public landing page exists. It must not include private contents, private hashes, private summaries, or extracted private text.

## Native-language rule

The native-language source remains authoritative. English summaries are convenience metadata only.

## Default evidence model

The default evidence model is:

```text
source URL + provenance metadata + access classification + rights classification + hash metadata
```

The default evidence model is not:

```text
raw document mirroring
```

## Current phase

P0: doctrine, governance, contribution boundaries, and public-source/non-advisory policy.

No production dataset should be treated as complete yet.

## Disclaimer

See [DISCLAIMER.md](DISCLAIMER.md).
