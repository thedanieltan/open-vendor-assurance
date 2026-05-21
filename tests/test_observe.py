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
    assert "Fetched public source successfully" in observation["notes"]


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
    assert "Maintainer review required" in observation["notes"]


def test_load_pilot_source_ids_includes_expected_sources():
    source_ids = observe.load_pilot_source_ids()
    assert "aws-subprocessors" in source_ids
    assert "google-cloud-subprocessors" in source_ids
    assert "microsoft-dpa" in source_ids
    assert "alibaba-cloud-international-subprocessors" in source_ids
    assert "tencent-cloud-international-subprocessors" in source_ids


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


def test_size_limited_response_is_classified_without_hashable_data(monkeypatch):
    class OversizedResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def geturl(self):
            return "https://example.com/large"

        def read(self, _limit):
            return b"x" * (observe.MAX_BYTES + 1)

    monkeypatch.setattr(observe.urllib.request, "urlopen", lambda _request, timeout: OversizedResponse())
    result, status, final_url, data = observe.fetch_public("https://example.com/large")

    assert result == "size_limited"
    assert status == 200
    assert final_url == "https://example.com/large"
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
    assert "does not bypass" in observation["notes"]


def test_ambiguous_results_are_identified():
    assert observe.is_ambiguous_result("bot_protected") is True
    assert observe.is_ambiguous_result("size_limited") is True
    assert observe.is_ambiguous_result("fetch_failed") is True
    assert observe.is_ambiguous_result("quarantined") is True
    assert observe.is_ambiguous_result("ok") is False


def test_observe_sources_skips_ambiguous_writes_by_default(monkeypatch):
    source = {
        "source_id": "example-source",
        "vendor_id": "example-vendor",
        "source_url": "https://example.com",
        "access_class": "public_web",
    }
    monkeypatch.setattr(observe, "select_sources", lambda pilot_only: [source])
    monkeypatch.setattr(
        observe,
        "observation_for_source",
        lambda _source: {
            "schema_version": "0.1.0",
            "observation_id": "example-source-2026-05-14",
            "vendor_id": "example-vendor",
            "source_id": "example-source",
            "artifact_id": None,
            "observed_at": "2026-05-14T00:00:00Z",
            "result": "bot_protected",
            "http_status": 403,
            "final_url": "https://example.com",
            "access_class": "public_web",
            "hashes": {"raw_sha256": "sha256:TBD", "normalized_text_sha256": "sha256:TBD", "etag": None, "last_modified": None},
            "storage": {"raw_document_stored": False, "extracted_text_stored": False, "screenshot_stored": False},
            "notes": "test",
        },
    )
    written = []
    monkeypatch.setattr(
        observe,
        "write_observation",
        lambda observation: written.append(observation) or observe.ROOT / "data/vendors/example-vendor/observations/x.yaml",
    )

    observe.observe_sources(dry_run=False, pilot_only=True)

    assert written == []


def test_observe_sources_can_write_ambiguous_when_explicitly_allowed(monkeypatch):
    source = {
        "source_id": "example-source",
        "vendor_id": "example-vendor",
        "source_url": "https://example.com",
        "access_class": "public_web",
    }
    observation = {
        "schema_version": "0.1.0",
        "observation_id": "example-source-2026-05-14",
        "vendor_id": "example-vendor",
        "source_id": "example-source",
        "artifact_id": None,
        "observed_at": "2026-05-14T00:00:00Z",
        "result": "bot_protected",
        "http_status": 403,
        "final_url": "https://example.com",
        "access_class": "public_web",
        "hashes": {"raw_sha256": "sha256:TBD", "normalized_text_sha256": "sha256:TBD", "etag": None, "last_modified": None},
        "storage": {"raw_document_stored": False, "extracted_text_stored": False, "screenshot_stored": False},
        "notes": "test",
    }
    monkeypatch.setattr(observe, "select_sources", lambda pilot_only: [source])
    monkeypatch.setattr(observe, "observation_for_source", lambda _source: observation)
    written = []
    monkeypatch.setattr(
        observe,
        "write_observation",
        lambda item: written.append(item) or observe.ROOT / "data/vendors/example-vendor/observations/x.yaml",
    )

    observe.observe_sources(dry_run=False, pilot_only=True, allow_ambiguous_write=True)

    assert written == [observation]


def test_dry_run_summary_is_compact(monkeypatch, capsys):
    source = {
        "source_id": "example-source",
        "vendor_id": "example-vendor",
        "source_url": "https://example.com",
        "access_class": "public_web",
    }
    monkeypatch.setattr(observe, "select_sources", lambda pilot_only: [source])
    monkeypatch.setattr(
        observe,
        "observation_for_source",
        lambda _source: {
            "schema_version": "0.1.0",
            "observation_id": "example-source-2026-05-14",
            "vendor_id": "example-vendor",
            "source_id": "example-source",
            "artifact_id": None,
            "observed_at": "2026-05-14T00:00:00Z",
            "result": "ok",
            "http_status": 200,
            "final_url": "https://example.com",
            "access_class": "public_web",
            "hashes": {"raw_sha256": "sha256:" + "a" * 64, "normalized_text_sha256": "sha256:" + "b" * 64, "etag": None, "last_modified": None},
            "storage": {"raw_document_stored": False, "extracted_text_stored": False, "screenshot_stored": False},
            "notes": "test",
        },
    )

    observe.observe_sources(dry_run=True, pilot_only=True)
    captured = capsys.readouterr().out

    assert "OpenVA observation summary" in captured
    assert "example-source: ok" in captured
    assert "schema_version:" not in captured
