from tools.openva.catalog_lifecycle import change_event, lifecycle_change_type


def test_lifecycle_change_type_maps_operations():
    assert lifecycle_change_type("create") == "created"
    assert lifecycle_change_type("refresh") == "updated"
    assert lifecycle_change_type("deprecate") == "metadata_changed"


def test_lifecycle_change_event_is_non_advisory():
    event = change_event(
        change_id="batch-cloudflare-dpa",
        vendor_id="cloudflare",
        source_id="cloudflare-dpa",
        artifact_id="cloudflare-dpa",
        change_type="created",
        detected_at="2026-05-15T00:00:00Z",
        summary="Catalog lifecycle operation create recorded for public source metadata.",
    )

    assert event["schema_version"] == "0.1.0"
    assert event["materiality"] == "unknown"
    assert event["review_state"] == "proposed"
    assert event["not_advice"] is True
