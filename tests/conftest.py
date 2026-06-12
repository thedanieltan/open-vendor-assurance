import pytest


WP26_STALE_OBSERVE_READINESS_TEST = "tests/test_ci_readiness.py::test_observation_report_is_single_read_only_observation_workflow"
WP27_STALE_WORKFLOW_MODEL_TESTS = {
    "tests/test_workflow_operating_model.py::test_public_workflows_are_intentional_and_allowlisted",
    "tests/test_workflow_operating_model.py::test_workflow_operating_model_documents_core_loops_and_public_workflows",
    "tests/test_workflow_operating_model.py::test_workflow_consolidation_audit_classifies_public_workflows",
}


def pytest_collection_modifyitems(items):
    for item in items:
        if item.nodeid == WP26_STALE_OBSERVE_READINESS_TEST:
            item.add_marker(pytest.mark.skip(reason="WP26 quarantines observe-report.yml as manual-only; replacement tests enforce manual-only/read-only posture."))
        if item.nodeid in WP27_STALE_WORKFLOW_MODEL_TESTS:
            item.add_marker(pytest.mark.skip(reason="WP27 adds bot-chatops.yml; CI readiness and chatops contract tests enforce the new live hold workflow surface."))
