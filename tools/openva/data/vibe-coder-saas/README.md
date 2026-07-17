# Vibe-coder developer SaaS directory

This directory is a curated vendor-identity input for OpenVA's existing breadth-replenishment worker.
It is not a second catalogue and none of its rows are canonical vendor or assurance facts.

## Inclusion rule

Include a SaaS vendor when an individual developer or small product team can reasonably sign up and use a developer-facing surface, including one or more of:

- an API or SDK;
- developer mode or developer workspace;
- test mode, sandbox, staging tenant, or demo environment;
- a practical free tier, free developer allowance, or free trial suitable for building and testing;
- a hosted app-building, deployment, database, identity, payment, communications, observability, AI, automation, content, commerce, testing, or data service commonly composed into generated applications.

Do not require the vendor to market itself specifically as a "vibe-coding" product. The cohort follows the services developers actually compose into applications.

## Maintenance rule

- Add new eligible vendors continuously; there is no vendor-count cap.
- Keep every `id` and `official_domain` unique across all CSV shards.
- Use the vendor-controlled public homepage or developer landing page as `listing_url`.
- Use ISO 3166-1 alpha-2 uppercase country codes for the observed headquarters country.
- Keep descriptions in the form `developer SaaS; <controlled category tags>`.
- Split or reorganize shards for maintainability without changing ingestion semantics; the worker reads every CSV file in this directory.
- Remove or correct a row when the identity or official domain is wrong. Access-model changes alone do not become assurance conclusions here and should be re-evaluated during periodic cohort maintenance.

## Governance boundary

The worker emits zero-weight, non-advisory `public_directory` identity signals. Existing identity collision checks, official-domain source discovery, source verification, eligibility, machine quorum, pull-request, release, and controlled-automerge gates remain authoritative before any vendor or source becomes canonical.
