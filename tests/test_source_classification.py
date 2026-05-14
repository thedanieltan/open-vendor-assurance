from tools.openva.validate import source_domain_allowed, validate_access_rights


def test_source_domain_allowed_by_official_domain():
    assert source_domain_allowed("vendor", "trust.example.com", ["example.com"], set())


def test_source_domain_allowed_by_exception():
    exceptions = {("vendor", "officialpublisher.example")}
    assert source_domain_allowed("vendor", "docs.officialpublisher.example", ["example.com"], exceptions)


def test_source_domain_rejects_unapproved_off_domain():
    assert not source_domain_allowed("vendor", "unofficial.example", ["example.com"], set())


def test_public_web_allows_metadata_only():
    assert validate_access_rights("record.yaml", {"access_class": "public_web", "rights_class": "metadata_only"}) == []


def test_excluded_non_public_requires_gated_excluded():
    failures = validate_access_rights("record.yaml", {"access_class": "excluded_non_public", "rights_class": "metadata_only"})
    assert failures


def test_public_landing_gated_docs_allows_gated_excluded():
    assert validate_access_rights("record.yaml", {"access_class": "public_landing_gated_docs", "rights_class": "gated_excluded"}) == []
