# Category Lane Execution Backlog

This backlog turns the metadata-based category taxonomy into an execution plan for breadth and depth work.

It is not a scoring system and does not express vendor approval, risk, suitability, certification, compliance, or procurement recommendations.

## Current gap

The first breadth/depth coverage audit showed that OpenVA is still thin:

```text
vendor_count: 62
artifact_count: 62
vendors_with_dpa: 11
vendors_with_subprocessors_list: 3
vendors_with_at_least_three_core_artifacts: 0
```

This backlog exists to prevent further shallow expansion.

## Execution model

Run two lanes in parallel:

```text
Lane A: materialize pending breadth manifests
Lane B: deepen tier-1 vendors with missing assurance artifacts
```

Every PR should declare whether it is:

```text
breadth expansion
depth enrichment
breadth + depth
materialization of pending batch manifests
source-quality tooling
```

## Core artifact types

```text
dpa
subprocessors_list
privacy_notice
security_page
trust_center
compliance_page
```

## Baseline targets

Minimum public-usefulness baseline:

```text
150 materialized vendors
top 25 tier-1 vendors with at least 4 core artifact types
no tier-1 vendor with only one artifact
materially improved DPA coverage
materially improved subprocessor-list coverage
```

Near-term maturity target:

```text
250 materialized vendors
top 50 vendors with at least 3 core artifact types
all major category lanes represented
APAC/mainland China coverage retained with native-language sources where available
```

## Lane A — materialize pending breadth manifests

The repo has many merged executable batch manifests whose vendors are not necessarily materialized into `data/vendors/` yet. These should be materialized in bounded PRs by lane.

### A1. Cloud, security, data, AI, and developer infrastructure

Manifests to inspect/materialize where still pending:

```text
catalog-batches/core-infrastructure-saas-expansion.yaml
catalog-batches/secops-cloud-expansion-1.yaml
catalog-batches/database-infra-expansion-1.yaml
catalog-batches/ai-data-tools-expansion-1.yaml
catalog-batches/devtools-ops-expansion-1.yaml
catalog-batches/storage-backup-expansion-1.yaml
```

Expected PR type:

```text
materialization of pending batch manifests
```

### A2. Payments, KYC, fintech, and data enrichment

Manifests to inspect/materialize where still pending:

```text
catalog-batches/payments-billing-expansion-1.yaml
catalog-batches/kyc-risk-expansion-1.yaml
catalog-batches/data-enrichment-expansion-1.yaml
catalog-batches/finance-procurement-expansion-1.yaml
```

Expected PR type:

```text
materialization of pending batch manifests
```

### A3. HR, healthcare, education, logistics, and workforce systems

Manifests to inspect/materialize where still pending:

```text
catalog-batches/hr-workforce-expansion-1.yaml
catalog-batches/healthcare-saas-expansion-1.yaml
catalog-batches/education-systems-expansion-1.yaml
catalog-batches/logistics-manufacturing-expansion-1.yaml
```

Expected PR type:

```text
materialization of pending batch manifests
```

### A4. Collaboration, commerce, marketing, GRC, content, support, and workflow software

Manifests to inspect/materialize where still pending:

```text
catalog-batches/project-planning-expansion-1.yaml
catalog-batches/product-research-expansion-1.yaml
catalog-batches/support-tools-expansion-1.yaml
catalog-batches/marketing-engagement-expansion-1.yaml
catalog-batches/grc-privacy-expansion-1.yaml
catalog-batches/trust-automation-expansion-1.yaml
catalog-batches/content-experimentation-expansion-1.yaml
catalog-batches/document-workflows-expansion-1.yaml
catalog-batches/commerce-web-expansion-1.yaml
catalog-batches/dashboards-expansion-1.yaml
catalog-batches/feedback-lms-expansion-1.yaml
```

Expected PR type:

```text
materialization of pending batch manifests
```

### A5. APAC, mainland China, and regional platforms

Manifests to inspect/materialize where still pending:

```text
catalog-batches/apac-saas-expansion-2.yaml
catalog-batches/p29-china-ai-cloud-saas.yaml
catalog-batches/p33-apac-saas.yaml
```

Expected PR type:

```text
materialization of pending batch manifests
```

## Lane B — deepen tier-1 vendors

Depth work should add public artifact records to existing vendors. Do not use gated, NDA, customer-only, portal-only, bespoke, or private materials.

### B1. Cloud and platform tier-1 vendors

Initial target vendors:

```text
microsoft
aws
google-cloud
alibaba-cloud
tencent-cloud
huawei-cloud
oracle-cloud
cloudflare
github
gitlab
atlassian
salesforce
```

Target missing artifact types:

```text
dpa
subprocessors_list
privacy_notice
security_page
trust_center
compliance_page
```

### B2. Payments, fintech, KYC, and risk tier-1 vendors

Initial target vendors:

```text
stripe
airwallex
twilio
shopify
zoho
```

After materialization, extend to:

```text
adyen
paypal
braintree
plaid
wise
trulioo
onfido
sumsub
persona
alloy
chainalysis
complyadvantage
```

### B3. HR, workforce, healthcare, and education tier-1 vendors

Initial target vendors:

```text
workday
culture-amp
deputy
employment-hero
keka
xero
```

After materialization, extend to:

```text
adp
rippling
deel
remote
bamboohr
greenhouse
lever
epic
oracle-health
canvas
powerschool
```

### B4. AI, data, developer, security, and observability tier-1 vendors

Initial target vendors:

```text
openai
snowflake
mongodb
datadog
vercel
figma
notion
```

After materialization, extend to:

```text
anthropic
cohere
huggingface
databricks
fivetran
dbt-labs
sentry
pagerduty
okta
crowdstrike
wiz
snyk
```

### B5. Collaboration, CRM, customer engagement, and marketing tier-1 vendors

Initial target vendors:

```text
hubspot
zendesk
intercom
mailchimp
braze
customer-io
klaviyo
zoom
canva
miro
monday-com
asana
clickup
airtable
box
```

After materialization, extend to:

```text
slack
freshdesk
helpscout
gorgias
typeform
surveymonkey
qualtrics
```

## PR size limits

Recommended PR limits:

```text
materialization PR: up to 50 vendors if generated cleanly
depth PR: 5 to 10 vendors when adding multiple artifacts each
sensitive-data categories: prefer smaller PRs with tighter review
```

## Stop conditions

Pause and create a correction PR if:

- duplicate vendors appear;
- semantic duplicate risk is high;
- many new records use only `other_public_artifact`;
- no DPA or subprocessor coverage improves;
- non-English sources are summarized only in English;
- generated indexes or pack files drift;
- any contributor proposes gated, NDA, private, portal-only, or customer-specific material.

## Review checklist

Every category-lane PR should confirm:

```text
- public-source-only materials
- no raw document mirroring
- no gated or private source use
- no legal/compliance/procurement/security advice
- native-language authority retained where relevant
- generated indexes rebuilt where records changed
- coverage audit delta is clear
```
