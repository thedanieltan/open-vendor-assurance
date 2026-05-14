from tools.openva.catalog_guard import validate_catalog_paths


def test_catalog_guard_allows_catalog_files():
    failures = validate_catalog_paths(
        [
            "data/vendors/example/vendor.yaml",
            "data/vendors/example/sources/example-source.yaml",
            "data/vendors/example/artifacts/example-artifact.yaml",
            "indexes/vendors.json",
            "openva-pack.json",
            "docs/coverage-map.md",
            "docs/vendor-expansion-backlog.md",
        ]
    )

    assert failures == []


def test_catalog_guard_rejects_substrate_files():
    failures = validate_catalog_paths(
        [
            "schemas/openva/source-reference.schema.json",
            "tools/openva/validate.py",
            "tests/test_validate.py",
            ".github/workflows/validate.yml",
            "policy/scope.md",
            "README.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "LICENSE",
            ".github/CODEOWNERS",
        ]
    )

    assert len(failures) == 10
    assert all("must not modify" in failure for failure in failures)


def test_catalog_guard_rejects_unknown_docs():
    failures = validate_catalog_paths(["docs/new-policy.md"])

    assert failures == ["docs/new-policy.md: catalog PR path is outside the allowed catalog-agent file set"]
