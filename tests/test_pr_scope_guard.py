"""Tests for the PR work-package scope guard (tools/openva/pr_scope_guard.py).

WP-LEGAL-ENTITY-EXPORT-RATIFICATION-01 item 5: a guard comparing a PR's changed paths
against its declared work-package scope, so unrelated ancestor work cannot silently
enter a PR. These test the pure matching logic, the committed manifest's
well-formedness, the dedicated scope-policy governance lane, the ADR/WP-02 split, and —
as a dogfood — that this PR's two-work-package change set stays within its declared
scopes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tools.openva.pr_scope_guard import (
    DeclarationError,
    allowed_globs,
    declared_work_package,
    load_manifest,
    out_of_scope_paths,
    scope_policy_operational_freshness_exemption,
)

ROOT = Path(__file__).resolve().parents[1]
HOSTED_DEPLOYMENT = ROOT / "docs" / "operations" / "contracts" / "hosted-deployment.yaml"

# Composite LOCKSTEP work package: the atomic first hosted-transport activation bundled
# with the seven ADR-0001 positioning files (WP-02A + WP-02L in one merge). It is a
# manifest-only wrapper (no slice_id); for the dependency mirror it stands in for WP-02A's
# hosted-deployment slice.
COMPOSITE_LOCKSTEP_WP = "WP-02A-L-HOSTED-TRANSPORT-POSITIONING-LOCKSTEP"
COMPOSITE_LOCKSTEP_STANDS_IN_FOR = "WP-02A-hosted-transport-api"

# The seven ADR-0001 positioning files. Six are OUTSIDE standalone WP-02A's scope
# (openva-match-service-contract.md is already a WP-02A doc), so they can only ride with
# the transport via the composite lockstep package.
ADR0001_POSITIONING_FILES = [
    "README.md",
    "docs/openva-match-service-contract.md",
    "docs/openva-match-service-deployment.md",
    "docs/public-launch-checklist.md",
    "docs/release-downloads.md",
    "docs/v0.1.0-public-launch-readiness.md",
    "docs/agent-export-contract.md",
]
POSITIONING_FILES_OUTSIDE_WP_02A = [f for f in ADR0001_POSITIONING_FILES if f != "docs/openva-match-service-contract.md"]

# The scope-policy machinery — governed SOLELY by WP-PR-SCOPE-POLICY-01.
SCOPE_POLICY_FILES = [
    "docs/operations/contracts/work-package-scope.yaml",
    "docs/operations/pr-scope-guard.md",
    "tools/openva/pr_scope_guard.py",
    "tests/test_pr_scope_guard.py",
    ".github/workflows/validate.yml",
    ".github/validation-ownership.yaml",
]

ASSURANCE_RELEASE_FILES = [
    "config/assurance-projection-policy.yaml",
    "docs/architecture/TEMPORAL_ASSURANCE_SCHEMA_V1.md",
    "docs/architecture/ASSURANCE_INTELLIGENCE_PROFILE_V1.md",
    "schemas/openva/assurance-record.schema.json",
    "schemas/openva/assurance-intelligence-projection.schema.json",
    "schemas/openva/vocabularies/assurance-intelligence-v1.schema.json",
    "tools/openva/assurance_intelligence.py",
    "tools/openva/assurance_projection.py",
    "tools/openva/schema_registry.py",
    "tools/openva/validate.py",
    "tests/support/__init__.py",
    "tests/support/assurance_fixture_repository.py",
    "tests/support/assurance_fixture_runner.py",
    "tests/test_assurance_intelligence_projection.py",
    "tests/test_assurance_schema_fixtures.py",
    "tests/fixtures/assurance/schema/valid/accredited-certification.json",
    "tests/fixtures/assurance/verification/contracts/no-observations/expectations.json",
    "tests/test_openva_mcp_metadata.py",
]

ASSURANCE_PUBLICATION_FILES = [
    ".github/workflows/site-pages.yml",
    "config/assurance-intelligence-publication-policy.yaml",
    "docs/architecture/ASSURANCE_INTELLIGENCE_PUBLICATION.md",
    "schemas/openva/assurance-intelligence-publication-policy.schema.json",
    "schemas/openva/assurance-intelligence-public-snapshot.schema.json",
    "site/build.py",
    "site/src/app.js",
    "site/src/styles.css",
    "tests/test_assurance_intelligence_publication.py",
    "tests/test_assurance_intelligence_publication_acceptance.py",
    "tests/test_release_artifacts.py",
    "tests/test_site.py",
    "tools/openva/assurance_intelligence_publication.py",
    "tools/openva/release_artifacts.py",
    "tools/openva/schema_registry.py",
]

SOURCE_HEALTH_LABEL_RECONCILIATION_WP = "WP-SOURCE-HEALTH-LABEL-RECONCILIATION-01"
SOURCE_HEALTH_LABEL_RECONCILIATION_FILES = [
    ".github/workflows/site-pages.yml",
    "site/build.py",
    "site/src/app.js",
    "tests/test_site.py",
    "tools/openva/site_discovery.py",
    "docs/source-trust/SOURCE_TRUST_OPERATIONS_RUNBOOK.md",
    "docs/source-trust/observation-retention-policy.md",
]

ASSURANCE_EVIDENCE_EXTRACTION_CONTRACT_WP = "WP-OPENVA-ASSURANCE-EVIDENCE-EXTRACTION-CONTRACT-01"
ASSURANCE_EVIDENCE_EXTRACTION_CONTRACT_FILES = [
    "config/assurance-evidence-extraction-policy.yaml",
    "docs/architecture/ASSURANCE_EVIDENCE_EXTRACTION_CONTRACT.md",
    "schemas/openva/assurance-evidence-extraction-policy.schema.json",
    "schemas/openva/assurance-evidence-extraction.schema.json",
    "tests/fixtures/assurance/evidence-extraction/valid/public-dpa-fact.json",
    "tests/test_assurance_evidence_extraction_contract.py",
    "tools/openva/assurance_evidence_extraction.py",
    "tools/openva/schema_registry.py",
    "tools/openva/validate.py",
]

GENERATED_CANDIDATE_PROMOTION_CATALOG_PR_FILES = [
    "data/vendors/guidewire/sources/guidewire-dpa.yaml",
    "data/vendors/guidewire/artifacts/guidewire-dpa.yaml",
    "data/vendors/guidewire/changes/candidate-promotion-guidewire-dpa.yaml",
    "dist/vendors/guidewire.json",
    "indexes/sources.json",
    "indexes/artifacts.json",
    "indexes/changes.json",
    "indexes/source-coverage.json",
    "indexes/summary.json",
    "indexes/vendor-match-index.json",
    "indexes/vendor-search.json",
    "maintenance/source-observations/latest-observations.json",
    "openva-pack.json",
]

CANDIDATE_PROMOTION_RUNTIME_FIX_FILES = [
    ".github/workflows/candidate-promotion-pr.yml",
    "tools/openva/catalog_guard.py",
    "tests/test_catalog_guard.py",
    "tests/test_candidate_promotion_workflow.py",
    "tests/test_wp41_workflows.py",
]

FRESHNESS_CONTINUITY_FILES = [
    ".github/workflows/observation-ledger-append-pr.yml",
    ".github/workflows/source-maintenance-report.yml",
    "docs/architecture/SOURCE_OBSERVATION_FRESHNESS_CONTINUITY.md",
    "maintenance/source-observations/latest-observations.json",
    "tests/test_observation_automerge.py",
    "tests/test_observation_ledger.py",
    "tests/test_observation_ledger_append_workflow.py",
    "tests/test_release_gates.py",
    "tests/test_source_maintenance_workflow.py",
    "tools/openva/observation_automerge.py",
    "tools/openva/observation_ledger.py",
    "tools/openva/release_gates.py",
]

# This PR (#403) is the bootstrap PR. It physically spans TWO work packages: the
# legal-entity ratification files and the scope-policy machinery. It escapes the guard
# only via the one-time self-bootstrap skip (base=main lacks the guard).
THIS_PR_LEGAL_ENTITY_FILES = [
    "docs/operations/legal-entity-export-ratification.md",
    "tests/test_legal_entity_export_ratification.py",
    "adapters/python/openva_vendor_inventory_matcher/openva_vendor_inventory_matcher/core.py",
    "tools/openva/agent_export.py",
    "integrations/mcp/openva_mcp/openva_mcp/matching.py",
    "tests/test_agent_export.py",
]
THIS_PR_SCOPE_POLICY_FILES = list(SCOPE_POLICY_FILES)

_MANIFEST = {
    "version": 1,
    "shared_allowed": [],
    "work_packages": {
        "WP-A": {"allowed_paths": ["tools/a/*", "tests/test_a.py"]},
        "WP-B": {"allowed_paths": ["docs/b.md"]},
    },
}


# --- pure matching logic -----------------------------------------------------


def test_in_scope_paths_pass():
    changed = ["tools/a/x.py", "tools/a/nested/y.py", "tests/test_a.py"]
    assert out_of_scope_paths(changed, "WP-A", _MANIFEST) == []


def test_out_of_scope_paths_are_flagged():
    changed = ["tools/a/x.py", "docs/b.md", "tools/c/z.py"]
    # docs/b.md belongs to WP-B; tools/c/z.py belongs to no declared scope.
    assert out_of_scope_paths(changed, "WP-A", _MANIFEST) == ["docs/b.md", "tools/c/z.py"]


def test_unknown_work_package_raises():
    with pytest.raises(KeyError):
        allowed_globs(_MANIFEST, "WP-DOES-NOT-EXIST")
    with pytest.raises(KeyError):
        out_of_scope_paths(["tools/a/x.py"], "WP-DOES-NOT-EXIST", _MANIFEST)


def test_star_glob_spans_path_separators():
    # `dir/*` must match nested files (fnmatchcase: * spans '/').
    assert out_of_scope_paths(["tools/a/deep/deeper/z.py"], "WP-A", _MANIFEST) == []


# --- committed manifest ------------------------------------------------------


def test_committed_manifest_is_well_formed():
    manifest = load_manifest()
    assert manifest["version"] == 1
    # shared_allowed is fail-closed: it MUST be a list, but MAY be empty.
    assert isinstance(manifest["shared_allowed"], list)
    wps = manifest["work_packages"]
    assert isinstance(wps, dict) and wps
    for wp_id, body in wps.items():
        assert wp_id.startswith("WP-"), wp_id
        assert body.get("allowed_paths"), f"{wp_id} must declare allowed_paths"
        assert isinstance(body["allowed_paths"], list)


def test_top_500_expansion_scope_is_limited_to_its_queue_contract():
    manifest = load_manifest()
    allowed = [
        "config/category-taxonomy.yaml",
        "maintenance/queues/catalog-growth-discovery.json",
        "tests/test_catalog_growth_discovery_queue.py",
    ]
    assert out_of_scope_paths(allowed, "WP-TOP-500-CATALOG-EXPANSION-01", manifest) == []
    assert out_of_scope_paths(
        ["data/vendors/example/vendor.yaml"], "WP-TOP-500-CATALOG-EXPANSION-01", manifest
    ) == ["data/vendors/example/vendor.yaml"]


def test_scope_manifest_contains_no_known_mojibake_markers():
    text = (ROOT / "docs" / "operations" / "contracts" / "work-package-scope.yaml").read_text(
        encoding="utf-8"
    )
    markers = [
        bytes.fromhex("c3a2e282ace2809d").decode("utf-8"),
        bytes.fromhex("c382c2b7").decode("utf-8"),
        bytes.fromhex("c3a2e282ace284a2").decode("utf-8"),
    ]
    assert [marker for marker in markers if marker in text] == []


# --- Task A: dedicated scope-policy governance lane ---------------------------


def test_unrelated_wp_cannot_edit_the_manifest():
    # 1. An unrelated WP changing the manifest is flagged out-of-scope.
    manifest = load_manifest()
    changed = ["docs/operations/contracts/work-package-scope.yaml"]
    assert out_of_scope_paths(changed, "WP-OPENVA-CANDIDATE-ACTIVATION-01", manifest) == changed


def test_unrelated_wp_cannot_edit_the_guard():
    # 2. An unrelated WP changing the guard tool is flagged out-of-scope.
    manifest = load_manifest()
    changed = ["tools/openva/pr_scope_guard.py"]
    assert out_of_scope_paths(changed, "WP-OPENVA-CANDIDATE-ACTIVATION-01", manifest) == changed


def test_unrelated_wp_cannot_edit_guard_tests_or_doc():
    # 3. An unrelated WP changing the guard tests AND the doc is flagged out-of-scope.
    manifest = load_manifest()
    changed = ["tests/test_pr_scope_guard.py", "docs/operations/pr-scope-guard.md"]
    assert out_of_scope_paths(changed, "WP-OPENVA-CANDIDATE-ACTIVATION-01", manifest) == sorted(changed)


def test_policy_wp_may_change_all_scope_policy_files():
    # 4. WP-PR-SCOPE-POLICY-01 may change all six scope-policy files.
    manifest = load_manifest()
    assert out_of_scope_paths(SCOPE_POLICY_FILES, "WP-PR-SCOPE-POLICY-01", manifest) == []


def test_scope_policy_files_are_exclusive_against_broad_globs():
    # 4b. The scope-policy files are EXCLUSIVE to WP-PR-SCOPE-POLICY-01: a non-policy work
    # package whose broad glob would otherwise match one (e.g. WP-02E declares
    # `.github/workflows/*`, `docs/operations/*`, and `tests/*`) is still blocked. This
    # keeps the policy that judges every PR un-editable under an unrelated declaration,
    # without having to narrow every broad glob in the manifest.
    manifest = load_manifest()
    # validate.yml and the manifest itself DO match WP-02E's broad globs, yet exclusivity
    # blocks them anyway (a plain glob check would let them through).
    glob_matched = [
        ".github/workflows/validate.yml",
        "docs/operations/contracts/work-package-scope.yaml",
    ]
    assert out_of_scope_paths(glob_matched, "WP-02E-SUPPLY-CHAIN", manifest) == sorted(glob_matched)
    # All six scope-policy files are out of scope for WP-02E.
    assert out_of_scope_paths(SCOPE_POLICY_FILES, "WP-02E-SUPPLY-CHAIN", manifest) == sorted(SCOPE_POLICY_FILES)
    # WP-02E may still change its own non-policy workflow + service surface.
    legit = [".github/workflows/release-image.yml", "services/openva_match_service/app.py"]
    assert out_of_scope_paths(legit, "WP-02E-SUPPLY-CHAIN", manifest) == []
    # The policy work package itself is unaffected by the exclusivity rule.
    assert out_of_scope_paths(SCOPE_POLICY_FILES, "WP-PR-SCOPE-POLICY-01", manifest) == []


def test_pr_cannot_self_authorize_a_manifest_widening():
    # 5. A PR declaring any non-policy WP that edits the manifest (to widen its own
    # allowlist) is flagged. The trusted-base evaluation in CI is what enforces this at
    # runtime; here we assert the manifest-edit-is-out-of-scope half.
    manifest = load_manifest()
    for wp in (
        "WP-LEGAL-ENTITY-EXPORT-RATIFICATION-01",
        "WP-OPENVA-AI-NATIVE-DISTRIBUTION-LEGAL-ENTITY",
        "WP-02A-HOSTED-TRANSPORT",
    ):
        changed = ["docs/operations/contracts/work-package-scope.yaml"]
        assert out_of_scope_paths(changed, wp, manifest) == changed, wp


def test_shared_allowed_contains_no_scope_policy_files():
    # 6. shared_allowed contains NONE of the six scope-policy files (no global exemption).
    manifest = load_manifest()
    shared = set(manifest.get("shared_allowed") or [])
    assert shared.isdisjoint(SCOPE_POLICY_FILES)


def test_bootstrap_cannot_recur_for_legal_entity_wp():
    # 7. The six scope-policy files are OUT of scope for the legal-entity WP, so no
    # future WP-LEGAL PR can touch them — this PR only did so via the one-time skip.
    manifest = load_manifest()
    violations = out_of_scope_paths(SCOPE_POLICY_FILES, "WP-LEGAL-ENTITY-EXPORT-RATIFICATION-01", manifest)
    assert set(violations) == set(SCOPE_POLICY_FILES)


def test_assurance_release_scope_covers_pillar_three_surface():
    manifest = load_manifest()
    assert out_of_scope_paths(ASSURANCE_RELEASE_FILES, "WP-OPENVA-ASSURANCE-RELEASE-01", manifest) == []


def test_assurance_release_scope_rejects_publication_catalog_and_source_maintenance_work():
    manifest = load_manifest()
    out_of_scope = [
        "data/vendors/example/vendor.yaml",
        "examples/vendors/example/assurances/example.yaml",
        ".github/workflows/validate.yml",
        ".github/workflows/site-pages.yml",
        "site/build.py",
        "tools/openva/assurance_intelligence_publication.py",
        "tools/openva/pr_scope_guard.py",
        "tools/openva/source_observer.py",
        "maintenance/source-observations/latest-observations.json",
        "docs/operations/contracts/work-package-scope.yaml",
    ]
    assert out_of_scope_paths(out_of_scope, "WP-OPENVA-ASSURANCE-RELEASE-01", manifest) == sorted(out_of_scope)


def test_assurance_publication_scope_covers_only_publication_surface():
    manifest = load_manifest()
    assert out_of_scope_paths(
        ASSURANCE_PUBLICATION_FILES, "WP-P4-ASSURANCE-INTELLIGENCE-PUBLICATION-01", manifest
    ) == []
    blocked = [
        "tools/openva/assurance_intelligence.py",
        "tests/test_assurance_intelligence_projection.py",
        "maintenance/source-observations/latest-observations.json",
        "schemas/openva/assurance-intelligence-projection.schema.json",
    ]
    assert out_of_scope_paths(
        blocked, "WP-P4-ASSURANCE-INTELLIGENCE-PUBLICATION-01", manifest
    ) == sorted(blocked)


def test_source_health_label_reconciliation_scope_covers_exact_composite_surface():
    manifest = load_manifest()
    assert out_of_scope_paths(
        SOURCE_HEALTH_LABEL_RECONCILIATION_FILES,
        SOURCE_HEALTH_LABEL_RECONCILIATION_WP,
        manifest,
    ) == []


def test_assurance_evidence_extraction_contract_scope_covers_prerequisite_surface():
    manifest = load_manifest()
    assert out_of_scope_paths(
        ASSURANCE_EVIDENCE_EXTRACTION_CONTRACT_FILES,
        ASSURANCE_EVIDENCE_EXTRACTION_CONTRACT_WP,
        manifest,
    ) == []


def test_autonomous_operational_scope_covers_generated_candidate_promotion_catalog_pr_outputs():
    manifest = load_manifest()
    assert out_of_scope_paths(
        GENERATED_CANDIDATE_PROMOTION_CATALOG_PR_FILES,
        "WP-AUTONOMOUS-OPERATIONAL-PR-CONTROL-PLANE-01",
        manifest,
    ) == []


def test_autonomous_operational_scope_covers_candidate_promotion_runtime_fix_surface():
    manifest = load_manifest()
    assert out_of_scope_paths(
        CANDIDATE_PROMOTION_RUNTIME_FIX_FILES,
        "WP-AUTONOMOUS-OPERATIONAL-PR-CONTROL-PLANE-01",
        manifest,
    ) == []


def test_source_health_label_reconciliation_scope_rejects_unlisted_paths():
    manifest = load_manifest()
    blocked = [
        "site/src/styles.css",
        "docs/source-trust/source-health.md",
        "public/assurance-intelligence.json",
        "tests/test_assurance_intelligence_publication.py",
    ]
    assert out_of_scope_paths(
        blocked,
        SOURCE_HEALTH_LABEL_RECONCILIATION_WP,
        manifest,
    ) == sorted(blocked)


def test_assurance_evidence_extraction_contract_scope_rejects_cohort_and_platform_work():
    manifest = load_manifest()
    blocked = [
        "data/vendors/adobe/assurances/adobe-public-dpa.yaml",
        "data/vendors/adobe/assurance_observations/adobe-public-dpa-observation.yaml",
        "maintenance/assurance-intelligence/latest/ad/adobe-public-dpa.json",
        "public/assurance-intelligence.json",
        "site/build.py",
        ".github/workflows/site-pages.yml",
        "services/openva_match_service/app.py",
        "schemas/openva/assurance-record.schema.json",
        "tools/openva/assurance_intelligence.py",
        "maintenance/source-observations/latest-observations.json",
    ]
    assert out_of_scope_paths(
        blocked,
        ASSURANCE_EVIDENCE_EXTRACTION_CONTRACT_WP,
        manifest,
    ) == sorted(blocked)


def test_freshness_continuity_scope_covers_only_observation_freshness_surface():
    manifest = load_manifest()
    assert out_of_scope_paths(
        FRESHNESS_CONTINUITY_FILES, "WP-SOURCE-OBSERVATION-FRESHNESS-CONTINUITY-01", manifest
    ) == []
    blocked = [
        "config/observation-sla.yaml",
        "maintenance/source-observations/events/2026-07.ndjson",
        "data/vendors/example/vendor.yaml",
        "tools/openva/assurance_intelligence.py",
        "schemas/openva/assurance-record.schema.json",
    ]
    assert out_of_scope_paths(
        blocked, "WP-SOURCE-OBSERVATION-FRESHNESS-CONTINUITY-01", manifest
    ) == sorted(blocked)


def test_policy_only_operational_freshness_exemption_accepts_pure_policy_pr():
    manifest = load_manifest()
    assert scope_policy_operational_freshness_exemption(
        SCOPE_POLICY_FILES, "WP-PR-SCOPE-POLICY-01", manifest
    )


def test_policy_only_operational_freshness_exemption_rejects_non_policy_and_mixed_paths():
    manifest = load_manifest()
    assert not scope_policy_operational_freshness_exemption(
        SCOPE_POLICY_FILES, "WP-OPENVA-ASSURANCE-RELEASE-01", manifest
    )
    assert not scope_policy_operational_freshness_exemption(
        ["docs/operations/contracts/work-package-scope.yaml", "tools/openva/assurance_projection.py"],
        "WP-PR-SCOPE-POLICY-01",
        manifest,
    )
    assert not scope_policy_operational_freshness_exemption([], "WP-PR-SCOPE-POLICY-01", manifest)


def test_validate_workflow_keeps_path_aware_release_gate_and_policy_exemption():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["repository-integrity"]["steps"]
    by_name = {step.get("name"): step for step in steps if step.get("name")}

    assert "Run OpenVA validator" in by_name
    assert "Rebuild generated indexes" in by_name
    assert "Check generated files are committed" in by_name
    assert "Determine scope-policy operational freshness exclusion" in by_name
    assert "Run source-intelligence release gates (pr profile)" in by_name

    release_gate = by_name["Run source-intelligence release gates (pr profile)"]
    release_condition = " ".join(release_gate["if"].split())
    assert "github.event_name != 'pull_request'" in release_condition
    assert "needs.pr-change-classifier.outputs.repository_integrity_heavy == 'true'" in release_condition
    assert "steps.scope_policy_freshness.outputs.skip_release_gates != 'true'" in release_condition

    probe = by_name["Determine scope-policy operational freshness exclusion"]["run"]
    assert "python -m tools.openva.pr_scope_guard --declaration-file" in probe
    assert 'found == ["WP-PR-SCOPE-POLICY-01"]' in probe
    assert "set(changed) <= exclusive" in probe
    assert "skip_release_gates=true" in probe
    assert "python -m tools.openva.release_gates check --profile pr" in release_gate["run"]


# --- Task B: ADR-0006 acceptance vs WP-02 implementation split ----------------


def test_adr_status_pr_cannot_bundle_wp_02a_implementation():
    # 8. An ADR-status PR that also bundles WP-02A implementation is flagged.
    manifest = load_manifest()
    changed = [
        "docs/architecture/decisions/ADR-0006-hosted-public-read-deployment.md",
        "services/openva_match_service/app.py",
    ]
    violations = out_of_scope_paths(changed, "WP-ADR-0006-STATUS-CHANGE", manifest)
    assert violations == ["services/openva_match_service/app.py"]


def test_wp_02_slices_do_not_silently_include_each_others_files():
    # 9. One WP-02 slice cannot silently include another slice's distinguishing files.
    manifest = load_manifest()
    # WP-02A (transport) may not touch 02B schema, 02C tools, 02I mcp, 02E workflow.
    wp_02a_intrusions = [
        "schemas/openva/foo.json",
        "tools/openva/x.py",
        "integrations/mcp/y.py",
        ".github/workflows/z.yml",
    ]
    assert out_of_scope_paths(wp_02a_intrusions, "WP-02A-HOSTED-TRANSPORT", manifest) == sorted(
        wp_02a_intrusions
    )
    # WP-02L (positioning/docs) may not touch the match service.
    assert out_of_scope_paths(
        ["services/openva_match_service/app.py"], "WP-02L-POSITIONING", manifest
    ) == ["services/openva_match_service/app.py"]


def _slice_dependency_map_from_hosted_deployment() -> dict[str, list[str]]:
    data = yaml.safe_load(HOSTED_DEPLOYMENT.read_text(encoding="utf-8"))
    return {s["id"]: list(s.get("depends_on") or []) for s in data["implementation_slices"]}


def test_depends_on_integrity_and_mirrors_hosted_deployment():
    # 10. depends_on integrity + slice graph mirrors hosted-deployment.yaml.
    manifest = load_manifest()
    wps = manifest["work_packages"]

    # Build the manifest's depends_on graph and the WP->slice_id map.
    manifest_deps: dict[str, list[str]] = {}
    slice_id_of: dict[str, str] = {}
    for wp_id, body in wps.items():
        deps = list((body or {}).get("depends_on") or [])
        manifest_deps[wp_id] = deps
        if (body or {}).get("slice_id"):
            slice_id_of[wp_id] = body["slice_id"]

    # (a) Every depends_on target exists in the manifest.
    for wp_id, deps in manifest_deps.items():
        for dep in deps:
            assert dep in wps, f"{wp_id} depends_on undeclared {dep}"

    # (b) The depends_on graph is acyclic.
    WHITE, GREY, BLACK = 0, 1, 2
    color = {wp: WHITE for wp in manifest_deps}

    def visit(node: str) -> None:
        color[node] = GREY
        for nxt in manifest_deps.get(node, []):
            assert color[nxt] != GREY, f"cycle detected at edge {node} -> {nxt}"
            if color[nxt] == WHITE:
                visit(nxt)
        color[node] = BLACK

    for wp in manifest_deps:
        if color[wp] == WHITE:
            visit(wp)

    # (c) WP-02A depends_on includes the ADR governance edge.
    assert "WP-ADR-0006-STATUS-CHANGE" in manifest_deps["WP-02A-HOSTED-TRANSPORT"]

    # (d) For each WP-02 slice, depends_on mapped to slice_ids (EXCLUDING the
    # WP-ADR-0006-STATUS-CHANGE governance edge) equals hosted-deployment.yaml.
    hosted = _slice_dependency_map_from_hosted_deployment()
    for wp_id, body in wps.items():
        slice_id = (body or {}).get("slice_id")
        if not slice_id:
            continue
        assert slice_id in hosted, f"{wp_id} slice_id {slice_id} missing from hosted-deployment.yaml"
        mapped = []
        for dep in manifest_deps[wp_id]:
            if dep == "WP-ADR-0006-STATUS-CHANGE":
                continue
            if dep == COMPOSITE_LOCKSTEP_WP:
                # The lockstep composite is a manifest-only wrapper (no slice_id); for the
                # dependency mirror it stands in for WP-02A's hosted-deployment slice (the
                # first hosted-transport activation it carries).
                mapped.append(COMPOSITE_LOCKSTEP_STANDS_IN_FOR)
                continue
            assert dep in slice_id_of, f"{wp_id} depends_on {dep} which has no slice_id"
            mapped.append(slice_id_of[dep])
        assert sorted(mapped) == sorted(hosted[slice_id]), (
            f"{wp_id} ({slice_id}) depends_on (minus ADR edge) {sorted(mapped)} "
            f"!= hosted-deployment {sorted(hosted[slice_id])}"
        )


# --- replacement dogfood tests (this PR spans TWO work packages) -------------


def test_this_prs_legal_entity_files_are_in_the_legal_entity_scope():
    # 11. The legal-entity subset of THIS PR's files is within WP-LEGAL-ENTITY-...-01.
    manifest = load_manifest()
    assert out_of_scope_paths(
        THIS_PR_LEGAL_ENTITY_FILES, "WP-LEGAL-ENTITY-EXPORT-RATIFICATION-01", manifest
    ) == []


def test_this_prs_scope_policy_files_are_in_the_policy_scope():
    # 12. The scope-policy subset of THIS PR's files is within WP-PR-SCOPE-POLICY-01.
    manifest = load_manifest()
    assert out_of_scope_paths(
        THIS_PR_SCOPE_POLICY_FILES, "WP-PR-SCOPE-POLICY-01", manifest
    ) == []


# --- work-package declaration (fail-closed) ----------------------------------


def test_declared_work_package_accepts_exactly_one():
    body = "Some PR description.\n\nWork-Package: WP-LEGAL-ENTITY-EXPORT-RATIFICATION-01\n\nMore text."
    assert declared_work_package(body) == "WP-LEGAL-ENTITY-EXPORT-RATIFICATION-01"


def test_declared_work_package_fails_closed_on_zero():
    with pytest.raises(DeclarationError):
        declared_work_package("A PR body with no declaration line.")


def test_declared_work_package_fails_closed_on_multiple():
    body = "Work-Package: WP-ONE\nWork-Package: WP-TWO\n"
    with pytest.raises(DeclarationError):
        declared_work_package(body)


def test_declared_work_package_repeated_same_id_is_one():
    body = "Work-Package: WP-ONE\n...\nWork-Package: WP-ONE\n"
    assert declared_work_package(body) == "WP-ONE"


def test_guard_would_have_caught_pr_400_contamination():
    # The exact failure: PR #400 (candidate-activation) inherited the legal-entity
    # commit, so its changed set spanned BOTH work packages. Declared as the
    # candidate-activation WP, the legal-entity files must be flagged out of scope.
    manifest = load_manifest()
    candidate_paths = [
        "tools/openva/candidate_record.py",
        "tools/openva/vendor_resolution.py",
        "config/automerge-policy.yaml",
    ]
    legal_entity_paths = [
        "tools/openva/agent_export.py",
        "adapters/python/openva_vendor_inventory_matcher/openva_vendor_inventory_matcher/core.py",
        "integrations/mcp/openva_mcp/openva_mcp/matching.py",
        "schemas/openva/agent-export.schema.json",
    ]
    violations = out_of_scope_paths(
        candidate_paths + legal_entity_paths, "WP-OPENVA-CANDIDATE-ACTIVATION-01", manifest
    )
    assert set(violations) == set(legal_entity_paths), (
        "the guard must flag the legal-entity files as outside the candidate-activation scope"
    )
    # And those same files ARE in scope for the legal-entity work package.
    assert out_of_scope_paths(legal_entity_paths, "WP-OPENVA-AI-NATIVE-DISTRIBUTION-LEGAL-ENTITY", manifest) == []


# --- Composite lockstep work package (WP-02A + WP-02L, atomic first activation) -------


def test_composite_lockstep_accepts_transport_and_positioning_files():
    # The composite accepts PRECISELY the WP-02A transport surface + the seven ADR-0001
    # positioning files under one declaration (the atomic lockstep merge).
    manifest = load_manifest()
    files = [
        "services/openva_match_service/openva_match_service/app.py",
        "docs/resolver-api.md",
        "tests/test_openva_match_service_verify.py",
        *ADR0001_POSITIONING_FILES,
    ]
    assert out_of_scope_paths(files, COMPOSITE_LOCKSTEP_WP, manifest) == []


def test_composite_lockstep_rejects_unrelated_documentation():
    # The composite uses EXACT positioning paths, not docs/** — unrelated docs stay out.
    manifest = load_manifest()
    unrelated = ["docs/roadmap.md", "docs/operations/contracts/hosted-deployment.yaml"]
    assert out_of_scope_paths(unrelated, COMPOSITE_LOCKSTEP_WP, manifest) == sorted(unrelated)


def test_standalone_wp_02a_still_rejects_positioning_files():
    # Standalone WP-02A is NOT independently mergeable for the first activation: it cannot
    # carry the six positioning files outside its scope, so it cannot be the lockstep merge.
    manifest = load_manifest()
    flagged = out_of_scope_paths(POSITIONING_FILES_OUTSIDE_WP_02A, "WP-02A-HOSTED-TRANSPORT", manifest)
    assert set(flagged) == set(POSITIONING_FILES_OUTSIDE_WP_02A)


def test_composite_lockstep_declaration_is_a_single_work_package():
    body = f"Combined lockstep slice.\n\nWork-Package: {COMPOSITE_LOCKSTEP_WP}\n\nmore text."
    assert declared_work_package(body) == COMPOSITE_LOCKSTEP_WP


def test_composite_lockstep_dependency_edges():
    # The composite depends on the ADR governance gate; the downstream code/CI slices that
    # previously depended on standalone WP-02A now depend on the composite (the real first
    # hosted-transport activation). The composite is a manifest-only wrapper (no slice_id).
    manifest = load_manifest()
    wps = manifest["work_packages"]
    assert COMPOSITE_LOCKSTEP_WP in wps
    assert "WP-ADR-0006-STATUS-CHANGE" in (wps[COMPOSITE_LOCKSTEP_WP].get("depends_on") or [])
    assert "slice_id" not in wps[COMPOSITE_LOCKSTEP_WP]
    for downstream in ("WP-02B-ASYNC-PERSISTENCE", "WP-02E-SUPPLY-CHAIN"):
        deps = wps[downstream].get("depends_on") or []
        assert COMPOSITE_LOCKSTEP_WP in deps, f"{downstream} must depend on the composite"
        assert "WP-02A-HOSTED-TRANSPORT" not in deps, f"{downstream} must not depend on standalone WP-02A"


# --- Roadmap/contract reconciliation lane (WP-02-ROADMAP-RECONCILIATION-01) ----

RECONCILIATION_WP = "WP-02-ROADMAP-RECONCILIATION-01"

# Scope-policy MACHINERY (everything except work-package-scope.yaml itself) stays SOLELY
# under WP-PR-SCOPE-POLICY-01; the reconciliation lane must NOT be able to touch it.
SCOPE_POLICY_MACHINERY = [f for f in SCOPE_POLICY_FILES if f != "docs/operations/contracts/work-package-scope.yaml"]


def test_reconciliation_lane_covers_its_doc_and_contract_surface():
    # The reconciliation lane may edit the roadmap, impl-plan, hosted-deployment contract,
    # the manifest (for the mirrored depends_on edges only), and the two drift tests.
    manifest = load_manifest()
    reconciliation_files = [
        "docs/roadmap.md",
        "docs/operations/hosted-deployment-implementation-plan.md",
        "docs/operations/contracts/hosted-deployment.yaml",
        "docs/operations/contracts/work-package-scope.yaml",
        "tests/test_hosted_deployment_docs.py",
        "tests/test_ai_native_distribution_docs.py",
    ]
    assert out_of_scope_paths(reconciliation_files, RECONCILIATION_WP, manifest) == []


def test_reconciliation_lane_cannot_touch_scope_policy_machinery():
    # The carve-out is narrow: the lane edits the manifest in lockstep with the contract,
    # but the guard/tests/doc/CI workflow/ownership map remain governed only by the policy WP.
    manifest = load_manifest()
    violations = out_of_scope_paths(SCOPE_POLICY_MACHINERY, RECONCILIATION_WP, manifest)
    assert set(violations) == set(SCOPE_POLICY_MACHINERY)


def test_reconciliation_lane_cannot_touch_service_or_infra_code():
    # Documentation/contract/drift-test reconciliation only — no service, schema, worker,
    # deployment-artifact, or infrastructure paths.
    manifest = load_manifest()
    intrusions = [
        "services/openva_match_service/app.py",
        "schemas/openva/hosted-job-record.schema.json",
        "tools/openva/worker.py",
        "infra/main.tf",
        ".github/workflows/deploy.yml",
    ]
    assert out_of_scope_paths(intrusions, RECONCILIATION_WP, manifest) == sorted(intrusions)
