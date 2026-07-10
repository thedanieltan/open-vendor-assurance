from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.openva.workspace import (
    Component,
    ROOT,
    Workspace,
    WorkspaceError,
    load_workspace,
    main,
    plan_workspace,
    topological_order,
    validate_workspace,
)


def test_repository_workspace_manifest_is_valid_and_complete() -> None:
    workspace = load_workspace(root=ROOT)

    assert workspace.version == 1
    assert set(workspace.components) == {
        "contract",
        "core-tools",
        "pack-reader",
        "csv-export",
        "jsonl-export",
        "sqlite-export",
        "inventory-matcher",
        "match-service",
        "mcp",
        "browser-site",
        "google-sheets",
        "operational-governance",
        "distribution-positioning",
        "hosted-deployment-contracts",
        "repository-control",
    }
    assert workspace.components["inventory-matcher"].dependencies == ("pack-reader",)
    assert workspace.components["mcp"].dependencies == ("contract", "inventory-matcher")
    assert workspace.components["google-sheets"].dependencies == ("match-service",)
    assert workspace.components["hosted-deployment-contracts"].dependencies == (
        "contract",
        "match-service",
    )


def test_pack_reader_change_expands_to_reverse_dependents() -> None:
    workspace = load_workspace(root=ROOT)
    plan = plan_workspace(
        workspace,
        ["adapters/python/openva_pack_reader/openva_pack_reader/reader.py"],
        root=ROOT,
    )

    assert plan.direct_components == ("pack-reader",)
    assert set(plan.affected_components) == {
        "pack-reader",
        "csv-export",
        "jsonl-export",
        "sqlite-export",
        "inventory-matcher",
        "match-service",
        "mcp",
        "google-sheets",
        "hosted-deployment-contracts",
    }
    assert plan.full_suite is False
    assert "tests/test_openva_pack_reader.py" in plan.test_paths
    assert "tests/test_openva_vendor_inventory_matcher.py" in plan.test_paths
    assert "tests/test_openva_mcp.py" in plan.test_paths
    assert "tests/test_hosted_deployment_docs.py" in plan.test_paths
    assert plan.build_order.index("pack-reader") < plan.build_order.index("inventory-matcher")
    assert plan.build_order.index("inventory-matcher") < plan.build_order.index("mcp")


def test_leaf_mcp_change_keeps_tests_targeted_but_installs_dependencies() -> None:
    workspace = load_workspace(root=ROOT)
    plan = plan_workspace(
        workspace,
        ["integrations/mcp/openva_mcp/openva_mcp/server.py"],
        root=ROOT,
    )

    assert plan.direct_components == ("mcp",)
    assert plan.affected_components == ("mcp",)
    assert plan.full_suite is False
    assert all("mcp" in path or "enrichment_parity" in path for path in plan.test_paths)
    assert plan.install_paths == (
        "adapters/python/openva_pack_reader",
        "adapters/python/openva_vendor_inventory_matcher",
        "integrations/mcp/openva_mcp",
    )


def test_shared_contract_change_requires_full_suite() -> None:
    workspace = load_workspace(root=ROOT)
    plan = plan_workspace(
        workspace,
        ["schemas/openva/vendor.schema.json"],
        root=ROOT,
    )

    assert plan.direct_components == ("contract",)
    assert plan.full_suite is True
    assert plan.test_paths == ("tests",)
    assert set(plan.affected_components) == set(workspace.components)


def test_unowned_change_fails_safe_to_full_suite() -> None:
    workspace = load_workspace(root=ROOT)
    plan = plan_workspace(workspace, ["unexpected/new-surface.txt"], root=ROOT)

    assert plan.full_suite is True
    assert plan.unmatched_files == ("unexpected/new-surface.txt",)
    assert "fallback" in plan.reason


def test_test_file_change_is_owned_by_its_component() -> None:
    workspace = load_workspace(root=ROOT)
    plan = plan_workspace(workspace, ["tests/test_openva_csv_export.py"], root=ROOT)

    assert plan.direct_components == ("csv-export",)
    assert plan.affected_components == ("csv-export",)
    assert plan.test_paths == ("tests/test_openva_csv_export.py",)


def test_policy_workflow_change_does_not_pull_unrelated_governance_suites() -> None:
    workspace = load_workspace(root=ROOT)
    plan = plan_workspace(workspace, [".github/workflows/validate.yml"], root=ROOT)

    assert plan.direct_components == ("repository-control",)
    assert "tests/test_pr_scope_guard.py" in plan.test_paths
    assert "tests/test_operational_pr_scope.py" not in plan.test_paths
    assert "tests/test_ai_native_distribution_docs.py" not in plan.test_paths
    assert "tests/test_hosted_deployment_docs.py" not in plan.test_paths


def test_specialised_governance_surfaces_select_their_own_drift_tests() -> None:
    workspace = load_workspace(root=ROOT)

    operational = plan_workspace(
        workspace,
        [".github/workflows/discovery-ledger-append-pr.yml"],
        root=ROOT,
    )
    assert set(operational.direct_components) == {
        "operational-governance",
        "repository-control",
    }
    assert "tests/test_operational_pr_scope.py" in operational.test_paths

    positioning = plan_workspace(workspace, ["docs/agent-integrations.md"], root=ROOT)
    assert set(positioning.direct_components) == {
        "distribution-positioning",
        "repository-control",
    }
    assert "tests/test_ai_native_distribution_docs.py" in positioning.test_paths

    hosted = plan_workspace(
        workspace,
        ["docs/operations/contracts/hosted-deployment.yaml"],
        root=ROOT,
    )
    assert set(hosted.direct_components) == {
        "hosted-deployment-contracts",
        "repository-control",
    }
    assert "tests/test_hosted_deployment_docs.py" in hosted.test_paths


def test_dependency_cycle_is_rejected() -> None:
    workspace = Workspace(
        version=1,
        fallback="full_suite",
        components={
            "alpha": Component(
                component_id="alpha",
                kind="test",
                manifests=(),
                change_patterns=("alpha/**",),
                test_patterns=(),
                dependencies=("beta",),
            ),
            "beta": Component(
                component_id="beta",
                kind="test",
                manifests=(),
                change_patterns=("beta/**",),
                test_patterns=(),
                dependencies=("alpha",),
            ),
        },
    )

    with pytest.raises(WorkspaceError, match="cycle"):
        validate_workspace(workspace, require_files=False)


def test_unknown_dependency_is_rejected() -> None:
    workspace = Workspace(
        version=1,
        fallback="full_suite",
        components={
            "alpha": Component(
                component_id="alpha",
                kind="test",
                manifests=(),
                change_patterns=("alpha/**",),
                test_patterns=(),
                dependencies=("missing",),
            )
        },
    )

    with pytest.raises(WorkspaceError, match="unknown dependencies"):
        validate_workspace(workspace, require_files=False)


def test_topological_order_includes_transitive_install_prerequisites() -> None:
    workspace = load_workspace(root=ROOT)
    order = topological_order(workspace, ["mcp"])

    assert order == ("contract", "pack-reader", "inventory-matcher", "mcp")


def test_cli_emits_machine_readable_plan(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        [
            "--root",
            str(ROOT),
            "plan",
            "--changed-file",
            "adapters/python/openva_jsonl_export/openva_jsonl_export/exporter.py",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["direct_components"] == ["jsonl-export"]
    assert payload["affected_components"] == ["jsonl-export"]
    assert payload["test_paths"] == ["tests/test_openva_jsonl_export.py"]


def test_manifest_paths_are_repository_relative() -> None:
    workspace = load_workspace(root=ROOT)
    for component in workspace.components.values():
        for manifest in component.manifests:
            assert not Path(manifest).is_absolute()
