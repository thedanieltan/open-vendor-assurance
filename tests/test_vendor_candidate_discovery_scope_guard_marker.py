from tools.openva.vendor_candidate_discovery import normalize_domain


def test_vendor_candidate_discovery_scope_guard_marker():
    assert normalize_domain("https://www.example.com/path") == "example.com"
