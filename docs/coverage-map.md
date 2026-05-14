# Coverage Map

This document tracks OpenVA coverage so future catalog expansion remains intentional.

The current catalog snapshot contains 17 vendor records, 17 source records, and 17 artifact records.

## Current vendor coverage

### Cloud infrastructure

- Alibaba Cloud
- Amazon Web Services
- Google Cloud
- Microsoft
- Oracle Cloud
- Tencent Cloud

### Enterprise SaaS and business platforms

- Atlassian
- Salesforce
- SAP
- ServiceNow
- Workday
- Zoom

### Security, network, and observability

- Cloudflare
- Datadog

### Data platforms and databases

- MongoDB
- Snowflake

### Fixtures

- Example Cloud

The fixture exists for schema validation only and should not be treated as catalog coverage.

## Regional coverage

### United States / global-headquartered vendors

- Amazon Web Services
- Atlassian is not US-headquartered but serves global markets
- Cloudflare
- Datadog
- Google Cloud
- Microsoft
- MongoDB
- Oracle Cloud
- Salesforce
- ServiceNow
- Snowflake
- Workday
- Zoom

### Mainland China vendors

- Alibaba Cloud
- Tencent Cloud

### Europe-headquartered vendors

- SAP

### APAC-headquartered vendors outside mainland China

- Atlassian

## Source-type coverage

### Current strength

The catalog is currently strong in conservative public entrypoints:

- trust center pages;
- security pages;
- subprocessor pages for the initial cloud providers;
- DPA/legal entrypoints for selected large cloud providers.

### Current weakness

The catalog is still thin in:

- direct DPA records;
- dedicated subprocessor records outside the cloud-provider seed set;
- privacy notice records;
- AI/data-use terms;
- product-specific security pages;
- regional legal pages;
- formal observation records;
- change-event records.

## Coverage gaps

### Vendor categories needing expansion

- developer platforms;
- identity and access management;
- password and secrets management;
- payments and financial infrastructure;
- communications APIs;
- customer support platforms;
- marketing automation platforms;
- productivity and collaboration platforms;
- APAC SaaS vendors;
- mainland China SaaS vendors beyond cloud infrastructure;
- Japan and Korea enterprise SaaS vendors;
- EU enterprise SaaS and infrastructure vendors.

### Evidence types needing expansion

- subprocessor lists;
- DPAs and data processing terms;
- privacy notices;
- security pages;
- trust centers;
- AI product terms;
- regional data residency pages;
- subprocessors by product or region;
- public changelogs for assurance materials.

## Expansion rule

Future expansion should prefer small batches of three to five vendors.

Each batch should state:

- the category being expanded;
- why the category matters;
- the source type used;
- whether the batch adds new edge cases;
- whether generated indexes and pack integrity checks pass.

Do not add vendors merely to increase count.
