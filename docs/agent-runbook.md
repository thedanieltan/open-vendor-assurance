# Agent Runbook

This runbook turns the agent control plane into repeatable operating steps.

## Before starting

1. Confirm the assigned phase label is free.
2. Confirm the branch name is agent-owned.
3. Confirm the requested work belongs to the correct lane.
4. Start from current `main`.
5. Keep the PR scope narrow.

## Phase check

Search existing PRs, issues, and branches for the intended phase label.

Do not use a phase label that is already assigned to another agent or lane.

## Lane selection

Use the catalog lane for:

```text
vendor additions
source metadata updates
catalog-batches manifests
indexes
openva-pack.json
coverage/backlog bookkeeping
```

Use the core lane for:

```text
schemas
tools
tests
workflows
governance
release policy
observation behavior
pack contract
README and launch docs
```

## Catalog batch workflow

1. Create a branch:

```bash
git checkout main
git pull origin main
git checkout -b agent-catalog-curator-pXX-theme
```

2. Create a manifest:

```text
catalog-batches/pXX-theme.yaml
```

3. Generate records:

```bash
python -m tools.openva.catalog_batch catalog-batches/pXX-theme.yaml --build-indexes
```

4. Validate:

```bash
python -m tools.openva.validate validate
pytest -q
```

5. Commit only intended files:

```text
catalog-batches/pXX-theme.yaml
data/vendors/**
indexes/**
openva-pack.json
```

6. Open PR:

```text
Catalog: PXX add {theme} catalog batch
```

## Source refinement workflow

1. Read the latest observation report artifact.
2. Identify ambiguous sources:

```text
bot_protected
size_limited
fetch_failed
quarantined
```

3. Search only for public vendor-controlled replacements.
4. Prefer source-specific pages over broad homepages.
5. Open a catalog PR only when replacements are clear.
6. Otherwise open or update a human-review issue.

## Observation review workflow

1. Review scheduled observation report output.
2. Summarize counts and human-review queue.
3. Do not write ambiguous observations by default.
4. Do not treat ambiguous results as vendor risk findings.

## Backlog workflow

1. Identify under-covered categories or regions.
2. Create candidate lists.
3. Mark whether each candidate has clear public trust/legal/security pages.
4. Do not expand the catalog unless assigned a phase.

## Required cleanup before commit

Remove generated Python cache and accidental lockfiles:

```bash
rm -f poetry.lock
git clean -fd tests/__pycache__ tools/__pycache__ tools/openva/__pycache__ 2>/dev/null || true
```

## PR body checklist

Every agent PR should state:

- what changed;
- which lane it belongs to;
- files touched;
- validation commands run;
- source/access boundaries;
- human-review notes;
- explicit exclusions.

## Merge posture

Agents do not merge their own PRs unless the maintainer explicitly asks them to and checks are green.

Agents must never force-push over another agent's branch or close another agent's PR without explicit instruction.
