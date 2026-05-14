import urllib.error

import pytest

from tools.openva import observe
from tools.openva.observe import observation_for_source


def test_observation_for_source_records_success(monkeypatch):
    source = {
        "source_id": "example-source",
        "vendor_id": "example-vendor",
        "source_url": "https://example.com/trust",
        "access_class": "public_web",
    }

    monkeypatch.setattr("tools.openva.observe.fetch_public", lambda url: ("ok", 200, url, b"<h1>Hello</h1>"))
    observation = observation_for_source(source)

    assert observation["result"] == "ok"
    assert observation["http_status"] == 200
    assert observation["hashes"]["raw_sha256"].startswith("sha256:")
    assert observation["hashes"]["normalized_text_sha256"].startswith("sha256:")
    assert observation["storage"]["raw_document_stored"] is False


def test_observation_for_source_does_not_hash_access_changed(monkeypatch):
    source = {
        "source_id": "example-source",
        "vendor_id": "example-vendor",
        "source_url": "https://example.com/private",
        "access_class": "public_web",
    }

    monkeypatch.setattr("tools.openva.observe.fetch_public", lambda url: ("access_changed", 403, url, b""))
    observation = observation_for_source(source)

    assert observation["result"] == "access_changed"
    assert observation["hashes"]["raw_sha256"] == "sha256:TBD"
    assert observation["hashes"]["normalized_text_sha256"] == "sha256:TBD"


def test_load_pilot_source_ids_includes_expected_sources():
    source_ids = observe.load_pilot_source_ids()
    assert "aws-sub-processors" in source_ids
    assert "google-cloud-subprocessors" in source_ids
    assert "microsoft-dpa" in source_ids


def test_select_sources_pilot_rejects_unknown_source(monkeypatch):
    monkeypatch.setattr(observe, "load_pilot_source_ids", lambda: {"missing-source"})
    with pytest.raises(ValueError, match="unknown source_id"):
        observe.select_sources(pilot_only=True)


def test_bot_protected_status_codes_are_classified(monkeypatch):
    def raise_forbidden(_request, timeout):
        raise urllib.error.HTTPError(
            url="https://example.com",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(observe.urllib.request, "urlopen", raise_forbidden)
    result, status, final_url, data = observe.fetch_public("https://example.com")
    assert result == "bot_protected"
    assert status == 403
    assert final_url == "https://example.com"
    assert data == b""


def test_blocked_page_text_becomes_bot_protected(monkeypatch):
    source = {
        "source_id": "example-source",
        "vendor_id": "example-vendor",
        "source_url": "https://example.com",
        "access_class": "public_web",
    }

    monkeypatch.setattr(
        observe,
        "fetch_public",
        lambda _url: ("ok", 200, "https://example.com", b"Checking your browser before accessing"),
    )

    observation = observe.observation_for_source(source)
    assert observation["result"] == "bot_protected"
    assert observation["hashes"]["raw_sha256"] == "sha256:TBD"
    assert observation["storage"]["raw_document_stored"] is False
