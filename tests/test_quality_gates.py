from tools.openva.validate import domain_matches


def test_domain_matches_exact_domain():
    assert domain_matches("example.com", ["example.com"])


def test_domain_matches_subdomain():
    assert domain_matches("trust.example.com", ["example.com"])


def test_domain_matches_www_prefix():
    assert domain_matches("www.example.com", ["example.com"])


def test_domain_rejects_lookalike_suffix():
    assert not domain_matches("badexample.com", ["example.com"])


def test_domain_rejects_other_domain():
    assert not domain_matches("example.org", ["example.com"])
