# Discovery Mesh intake recovery

## Purpose

`discovery-mesh-intake-recovery.yml` converts a completed full-catalog Discovery Mesh aggregate artifact into reviewable repository transactions. It exists because discovery evidence can scale far beyond the practical file and payload size of one pull request.

The workflow does not reduce catalog breadth, candidate count, source depth, or total promotion actions. Transaction budgets control only the size of each repository mutation. The complete action set is deterministically partitioned and every action remains traceable to the exact source workflow run and parent promotion-plan digest.

The aggregate job no longer creates one monolithic intake branch. `discovery-mesh.yml` finishes after validating and uploading its aggregate evidence. The recovery workflow is the sole post-aggregate intake transaction owner; `candidate-promotion-pr.yml` remains the sole canonical source mutation authority.

## Triggering

The workflow runs after completed `discovery-mesh` executions whose source event is `schedule` or `workflow_dispatch`. It can also be dispatched manually with an exact source workflow run ID to recover an aggregate artifact from a prior failed intake transaction.

Push deployment smokes and pull-request promotion handoffs are excluded because they do not carry a full production intake artifact.

## Evidence contract

The source run must contain exactly one `openva-discovery-mesh-aggregate` artifact with:

- one `source-discovery-report.json`;
- one strict Discovery Mesh promotion plan;
- one Discovery Mesh health report;
- the stable vendor-breadth ledger, queue, candidates, and provider metrics when breadth state changed.

The workflow fails closed on missing or ambiguous evidence, invalid health posture, missing plan-referenced candidates, duplicate candidate paths, or out-of-scope repository changes.

## Partitioning and replay

Source actions are ordered deterministically and grouped by vendor where the repository transaction budgets permit. A vendor larger than one transaction may span multiple transactions, but candidate records are never split internally and every candidate path appears exactly once.

Each partition receives:

- a deterministic ID and branch name;
- the exact noncanonical candidate files referenced by the partition;
- one partition-specific promotion plan;
- the source run ID and parent plan digest;
- a pull request using the existing `Ops: stage discovery mesh candidates` handoff contract;
- the existing `WP-AUTONOMOUS-OPERATIONAL-PR-CONTROL-PLANE-01` declaration governing generated candidate and plan paths.

Stable breadth projections are committed through a separate breadth checkpoint transaction so source-depth volume cannot overwrite or obscure the durable identity queue.

Reruns first search for the exact deterministic branch and pull request. Existing pull requests are reused. A workflow-owned orphan branch is resumed only when its commit subject matches the expected source-run and partition identity; otherwise execution fails closed.

## Authority boundary

The recovery workflow writes only:

- noncanonical candidate-source records;
- partition-specific reviewed promotion plans;
- stable noncanonical vendor-breadth projections.

It never writes canonical vendors or sources and does not alter admission, verification, release, quorum, or automerge policy. After a source partition merges, `discovery-mesh.yml` resolves its exact plan and dispatches `candidate-promotion-pr.yml`, which remains the sole canonical source mutation authority.

## Operational acceptance

A recovered run is operationally accepted when:

1. the intake manifest accounts for every viable action exactly once;
2. all required breadth and source partition pull requests are opened or reused;
3. every pull request passes the existing repository validation and review controls;
4. merged source partitions dispatch the exact-plan canonical promotion workflow;
5. the receipt artifact reconciles every partition to a no-change, reused, recovered, or opened terminal transaction state.

Implementation acceptance is not public catalog acceptance. Public acceptance requires the resulting canonical promotions to merge, regenerate the site and exports, and become searchable on the live resolver.
