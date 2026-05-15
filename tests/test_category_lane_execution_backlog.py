from pathlib import Path

DOC = Path("docs/category-lane-execution-backlog.md")


def test_category_lane_execution_backlog_exists_and_sets_targets():
    text = DOC.read_text(encoding="utf-8")

    assert "150 materialized vendors" in text
    assert "250 materialized vendors" in text
    assert "top 25 tier-1 vendors with at least 4 core artifact types" in text
    assert "vendors_with_dpa: 11" in text
    assert "vendors_with_subprocessors_list: 3" in text


def test_category_lane_execution_backlog_separates_breadth_and_depth():
    text = DOC.read_text(encoding="utf-8")

    assert "Lane A: materialize pending breadth manifests" in text
    assert "Lane B: deepen tier-1 vendors with missing assurance artifacts" in text
    assert "materialization of pending batch manifests" in text
    assert "depth enrichment" in text


def test_category_lane_execution_backlog_covers_major_lanes():
    text = DOC.read_text(encoding="utf-8")

    required_lanes = [
        "Cloud, security, data, AI, and developer infrastructure",
        "Payments, KYC, fintech, and data enrichment",
        "HR, healthcare, education, logistics, and workforce systems",
        "Collaboration, commerce, marketing, GRC, content, support, and workflow software",
        "APAC, mainland China, and regional platforms",
        "Cloud and platform tier-1 vendors",
        "Payments, fintech, KYC, and risk tier-1 vendors",
        "HR, workforce, healthcare, and education tier-1 vendors",
        "AI, data, developer, security, and observability tier-1 vendors",
        "Collaboration, CRM, customer engagement, and marketing tier-1 vendors",
    ]

    for lane in required_lanes:
        assert lane in text


def test_category_lane_execution_backlog_preserves_source_and_non_advisory_boundaries():
    text = DOC.read_text(encoding="utf-8")

    assert "public-source-only materials" in text
    assert "no raw document mirroring" in text
    assert "no gated or private source use" in text
    assert "no legal/compliance/procurement/security advice" in text
    assert "native-language authority retained" in text
    assert "gated, NDA, private, portal-only, or customer-specific material" in text
