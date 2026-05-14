from tools.openva.url_safety import is_safe_public_url, validate_url_safety


def test_allows_https_public_domain():
    assert is_safe_public_url("https://example.com/trust")


def test_rejects_javascript_scheme():
    assert validate_url_safety("javascript:alert(1)")


def test_rejects_file_scheme():
    assert validate_url_safety("file:///etc/passwd")


def test_rejects_localhost():
    assert validate_url_safety("http://localhost:8000/private")


def test_rejects_loopback_ip():
    assert validate_url_safety("http://127.0.0.1/private")


def test_rejects_private_ipv4():
    assert validate_url_safety("http://10.0.0.5/metadata")


def test_rejects_link_local_metadata_ip():
    assert validate_url_safety("http://169.254.169.254/latest/meta-data")


def test_rejects_ipv6_loopback():
    assert validate_url_safety("http://[::1]/private")
