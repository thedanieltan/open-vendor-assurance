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
