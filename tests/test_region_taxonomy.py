from tools.openva.validate import (
    load_region_tags,
    load_vendor_category_tags,
    validate_region_tags,
    validate_vendor_category_tags,
)


def test_region_taxonomy_includes_core_market_tags():
    tags = load_region_tags()

    assert {"global", "apac", "sea", "eu", "sg", "us", "cn", "hk"}.issubset(tags)


def test_region_tags_accept_controlled_lowercase_values():
    failures = validate_region_tags("data/vendors/example/vendor.yaml", "regions_served", ["global", "apac", "sg"], load_region_tags())

    assert failures == []


def test_region_tags_reject_uppercase_values():
    failures = validate_region_tags("data/vendors/example/vendor.yaml", "regions_served", ["SG"], load_region_tags())

    assert "data/vendors/example/vendor.yaml: regions_served tag SG must be lowercase" in failures
    assert "data/vendors/example/vendor.yaml: regions_served tag SG is not defined in config/region-taxonomy.yaml" in failures


def test_region_tags_reject_unknown_values():
    failures = validate_region_tags("data/vendors/example/vendor.yaml", "regions_served", ["asia-pacific"], load_region_tags())

    assert failures == [
        "data/vendors/example/vendor.yaml: regions_served tag asia-pacific is not defined in config/region-taxonomy.yaml"
    ]


def test_vendor_category_tags_accept_controlled_values():
    failures = validate_vendor_category_tags(
        "data/vendors/example/vendor.yaml",
        ["cloud_infrastructure"],
        load_vendor_category_tags(),
    )

    assert failures == []


def test_vendor_category_tags_reject_unknown_values():
    failures = validate_vendor_category_tags(
        "data/vendors/example/vendor.yaml",
        ["finance_platform"],
        load_vendor_category_tags(),
    )

    assert failures == [
        "data/vendors/example/vendor.yaml: vendor_categories tag finance_platform is not defined in config/category-taxonomy.yaml"
    ]
