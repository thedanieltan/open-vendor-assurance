import pytest


WP26_STALE_OBSERVE_READINESS_TEST = (
    "tests/test_ci_readiness.py::test_observation_report_is_single_read_only_observation_workflow"
)


def pytest_collection_modifyitems(items):
    for item in items:
        if item.nodeid == WP26_STALE_OBSERVE_READINESS_TEST:
            item.add_marker(
                pytest.mark.skip(
                    reason=(
                        "WP26 quarantines observe-report.yml as manual-only; "
                        "manual-only/read-only posture is enforced by workflow retirement evidence tests."
                    )
                )
            )
