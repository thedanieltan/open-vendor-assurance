from tools.openva.automerge_lanes import load_policy


def strict_growth_policy():
    return load_policy()["strict_growth"]


def test_strict_growth_policy_defines_separate_wired_lane():
    policy = load_policy()

    assert policy["lanes"]["strict_growth"]["label"] == "automerge:strict-growth"
    assert policy["lanes"]["strict_growth"]["required_labels"] == ["catalog-growth"]
    assert policy["lanes"]["strict_growth"]["execution_wired"] is True
    assert policy["strict_growth"]["label"] == "automerge:strict-growth"
    assert policy["strict_growth"]["execution_wired"] is True


def test_strict_growth_policy_limits_are_configured_not_hardcoded():
    policy = strict_growth_policy()

    assert policy["max_new_vendors_per_pr"] == 5
    assert policy["max_sources_per_new_vendor"] == 2
    assert policy["freshness_hours"] == 4
    assert policy["core_source_types"] == [
        "dpa",
        "subprocessors_list",
        "privacy_notice",
        "security_page",
    ]
    assert policy["source_type_priority"] == [
        "dpa",
        "privacy_notice",
        "subprocessors_list",
        "security_page",
    ]


def test_strict_growth_policy_inference_sets_are_disjoint_and_explicit():
    policy = strict_growth_policy()

    allowed = set(policy["allowed_inference_modes"])
    blocked = set(policy["blocked_inference_modes"])
    assert allowed
    assert blocked
    assert allowed.isdisjoint(blocked)
    assert "none" in allowed
    assert "unknown" in blocked


def test_strict_growth_policy_relationship_prefixes_are_non_empty():
    prefixes = strict_growth_policy()["relationship_type_prefixes"]

    assert prefixes
    assert all(isinstance(prefix, str) and prefix for prefix in prefixes)
    assert "vendor_stated_" in prefixes
    assert "registry_stated_" in prefixes


def test_strict_growth_policy_action_id_fields_are_stable_semantic_fields():
    assert strict_growth_policy()["action_id_fields"] == [
        "vendor.candidate_vendor_id",
        "source.source_type_candidate",
        "source.candidate_source_id",
    ]
