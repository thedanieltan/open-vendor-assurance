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
