# Contributing

Contributions are welcome, but this repository uses strict evidence, source, and wording rules.

## What this project accepts

OpenVA accepts factual metadata about public vendor-published assurance materials, including:

- public DPA references;
- public subprocessor list references;
- public privacy notices;
- public trust-center landing pages;
- public security or compliance pages;
- public certification reference pages;
- public KYC or AML statements where relevant;
- public AI/data terms where relevant;
- source observation metadata;
- factual questionnaire or evidence request templates.

## What this project rejects

Do not submit:

- bespoke agreements;
- customer-specific contracts;
- order forms;
- private customer documents;
- NDA-gated materials;
- authenticated trust-center exports;
- private SOC reports;
- private ISO certificates;
- customer portal downloads;
- content requiring login, sales approval, customer status, support ticket access, or credentials;
- legal conclusions;
- compliance conclusions;
- procurement recommendations;
- vendor risk scores;
- security ratings;
- claims that a vendor is compliant, safe, certified, adequate, approved, suitable, or recommended.

## Source rules

A source must be public. Public means accessible without login, credentials, NDA, customer status, sales approval, private portal access, support ticket access, or anti-bot bypass.

If a public page points to gated documents, record only the public page metadata. Do not include gated contents, gated document hashes, summaries of gated documents, or extracted gated text.

## Language rules

The native-language source remains authoritative.

For non-English sources:

1. preserve native title where practical;
2. preserve native factual summary where practical;
3. mark English summaries as convenience metadata;
4. do not convert translation into advice or legal interpretation.

## Wording rules

Use factual wording:

- "Vendor publishes a public page describing..."
- "The public source references..."
- "The source is a public DPA page..."

Avoid advisory wording:

- "compliant"
- "safe"
- "approved"
- "adequate"
- "recommended"
- "suitable"
- "satisfies obligations"
- "meets requirements"

## Pull requests

Pull requests must:

- identify the public source;
- classify source access;
- classify rights status;
- preserve native-language context where relevant;
- avoid advisory language;
- explain whether any generated files were updated;
- pass validation checks once P1/P2 tooling is added.
