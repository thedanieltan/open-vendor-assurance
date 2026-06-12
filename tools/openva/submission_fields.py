"""Shared field-label contract between WP30 submission issue forms and the
WP31 submission verifier.

GitHub renders issue-form responses as ``### <field label>`` headings, so the
label text (not the form field id) is the parsing key. This module is the
single source of truth for those labels; a drift test asserts that every
entry matches the issue-form YAML under ``.github/ISSUE_TEMPLATE/``.
"""

from __future__ import annotations

NEW_VENDOR = "new_vendor"
NEW_SOURCE = "new_source"
BROKEN_SOURCE = "broken_source"
VENDOR_IDENTITY = "vendor_identity"
SUBPROCESSOR_FEED = "subprocessor_feed"
MACHINE_READABLE = "machine_readable"

FORM_TEMPLATES: dict[str, str] = {
    NEW_VENDOR: "submission-new-vendor.yml",
    NEW_SOURCE: "submission-new-source.yml",
    BROKEN_SOURCE: "submission-broken-source.yml",
    VENDOR_IDENTITY: "submission-vendor-identity.yml",
    SUBPROCESSOR_FEED: "submission-subprocessor-feed.yml",
    MACHINE_READABLE: "submission-machine-readable.yml",
}

TITLE_PREFIXES: dict[str, str] = {
    NEW_VENDOR: "Vendor candidate: ",
    NEW_SOURCE: "Source candidate: ",
    BROKEN_SOURCE: "Broken source: ",
    VENDOR_IDENTITY: "Vendor identity: ",
    SUBPROCESSOR_FEED: "Subprocessor feed: ",
    MACHINE_READABLE: "Machine-readable surface: ",
}

# field_id -> rendered heading label, per form. Only fields the verifier
# parses are listed; checkbox groups are not parsed.
FORM_FIELD_LABELS: dict[str, dict[str, str]] = {
    NEW_VENDOR: {
        "vendor_name": "Vendor name",
        "vendor_domain": "Vendor domain",
        "vendor_legal_name": "Vendor legal name",
        "headquarters_country": "Headquarters country",
        "known_public_sources": "Known public assurance source URLs",
        "public_access_confirmed": "Public access confirmed",
        "machine_readable_surface": "Machine-readable surface",
    },
    NEW_SOURCE: {
        "vendor_name": "Vendor name",
        "vendor_domain": "Vendor domain",
        "openva_vendor_id": "OpenVA vendor ID",
        "source_url": "Source URL",
        "source_type": "Source type",
        "canonical_location_belief": "Canonical location belief",
        "public_access_confirmed": "Public access confirmed",
        "machine_readable_surface": "Machine-readable surface",
    },
    BROKEN_SOURCE: {
        "vendor_name": "Vendor name",
        "vendor_domain": "Vendor domain",
        "source_url": "Existing source URL or OpenVA source ID",
        "observed_state": "Observed state",
        "replacement_url": "Replacement URL",
        "source_type": "Source type",
        "public_access_confirmed": "Public access confirmed",
    },
    VENDOR_IDENTITY: {
        "vendor_name": "Vendor name",
        "vendor_domain": "Vendor domain",
        "previous_vendor_name": "Previous vendor name",
        "previous_vendor_domain": "Previous vendor domain",
        "announcement_url": "Public announcement URL",
        "public_access_confirmed": "Public access confirmed",
    },
    SUBPROCESSOR_FEED: {
        "vendor_name": "Vendor name",
        "vendor_domain": "Vendor domain",
        "source_url": "Feed URL",
        "subprocessor_list_url": "Subprocessor list URL",
        "machine_readable_surface": "Machine-readable surface",
        "public_access_confirmed": "Public access confirmed",
    },
    MACHINE_READABLE: {
        "vendor_name": "Vendor name",
        "vendor_domain": "Vendor domain",
        "source_url": "Surface URL",
        "machine_readable_surface": "Machine-readable surface",
        "related_source_url": "Related source URL",
        "source_type": "Source type",
        "public_access_confirmed": "Public access confirmed",
    },
}

# Verification never echoes free-text fields; they are intentionally absent
# from FORM_FIELD_LABELS so the verifier cannot read them by field id.

TARGET_URL_FIELDS: dict[str, str | None] = {
    NEW_VENDOR: None,  # verify https://{vendor_domain}/ instead
    NEW_SOURCE: "source_url",
    BROKEN_SOURCE: "source_url",
    VENDOR_IDENTITY: "announcement_url",
    SUBPROCESSOR_FEED: "source_url",
    MACHINE_READABLE: "source_url",
}

FORM_LABELS: dict[str, tuple[str, ...]] = {
    NEW_VENDOR: ("submission:new-vendor",),
    NEW_SOURCE: ("submission:new-source",),
    BROKEN_SOURCE: ("submission:broken-source",),
    VENDOR_IDENTITY: ("submission:vendor-identity",),
    SUBPROCESSOR_FEED: ("submission:new-source", "submission:machine-readable"),
    MACHINE_READABLE: ("submission:machine-readable",),
}


def detect_form_kind(issue_title: str, issue_labels: list[str] | None = None) -> str | None:
    title = issue_title or ""
    for kind, prefix in TITLE_PREFIXES.items():
        if title.startswith(prefix.rstrip()):
            return kind
    labels = set(issue_labels or [])
    if {"submission:new-source", "submission:machine-readable"} <= labels:
        return SUBPROCESSOR_FEED
    fallback = {
        "submission:new-vendor": NEW_VENDOR,
        "submission:broken-source": BROKEN_SOURCE,
        "submission:vendor-identity": VENDOR_IDENTITY,
        "submission:machine-readable": MACHINE_READABLE,
        "submission:new-source": NEW_SOURCE,
    }
    for label, kind in fallback.items():
        if label in labels:
            return kind
    return None


def parse_submission_fields(form_kind: str, sections: dict[str, str]) -> dict[str, str]:
    """Map parsed ``### <heading>`` sections to field ids for one form kind."""
    labels = FORM_FIELD_LABELS.get(form_kind, {})
    return {
        field_id: sections.get(label, "").strip()
        for field_id, label in labels.items()
    }
