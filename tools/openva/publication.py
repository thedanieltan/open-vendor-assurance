"""Canonical publication configuration.

All OpenVA-owned public URLs (vendor pages, sitemap, robots.txt, llms.txt, the
discovery manifest, and the agent integration page) derive from a single
configuration file so that a host or domain change is a one-line edit rather
than a repository-wide find-and-replace. Generators must read URLs from here
instead of embedding their own base URL.

Paths under the canonical base are fixed by the agent export contract
(`docs/agent-export-contract.md`); only the base URL and a small set of
top-level paths are configurable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from tools.openva.indexes import ROOT

DEFAULT_CONFIG_PATH = ROOT / "config" / "publication.yaml"

REQUIRED_FIELDS = (
    "project_name",
    "canonical_base_url",
    "repository_url",
    "release_url",
    "agent_index_path",
)

# Export-contract paths served under the canonical base. These mirror the
# fixed file names emitted by tools.openva.agent_export and must not drift.
VENDOR_INDEX_PATH = "public/vendors/index.json"
SOURCE_INDEX_PATH = "public/sources/index.json"
VENDOR_EXPORT_PATH_TEMPLATE = "public/vendors/{vendor_id}.json"
AGENTS_PAGE_PATH = "agents/"
VENDORS_PAGE_PATH_TEMPLATE = "vendors/{vendor_id}/"


@dataclass(frozen=True)
class PublicationConfig:
    project_name: str
    canonical_base_url: str
    repository_url: str
    release_url: str
    agent_index_path: str

    def url(self, path: str) -> str:
        """Join a repository-relative path onto the canonical base URL."""
        return f"{self.canonical_base_url}/{path.lstrip('/')}"

    @property
    def agent_index_url(self) -> str:
        return self.url(self.agent_index_path)

    @property
    def vendor_index_url(self) -> str:
        return self.url(VENDOR_INDEX_PATH)

    @property
    def source_index_url(self) -> str:
        return self.url(SOURCE_INDEX_PATH)

    @property
    def agents_url(self) -> str:
        return self.url(AGENTS_PAGE_PATH)

    @property
    def export_contract_url(self) -> str:
        return f"{self.repository_url}/blob/main/docs/agent-export-contract.md"

    def vendor_export_url(self, vendor_id: str) -> str:
        return self.url(VENDOR_EXPORT_PATH_TEMPLATE.format(vendor_id=vendor_id))

    def vendor_page_url(self, vendor_id: str) -> str:
        return self.url(VENDORS_PAGE_PATH_TEMPLATE.format(vendor_id=vendor_id))


def load_publication_config(path: Path = DEFAULT_CONFIG_PATH) -> PublicationConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: publication config must be a mapping")
    missing = [field for field in REQUIRED_FIELDS if not raw.get(field)]
    if missing:
        raise ValueError(f"{path}: missing required publication fields {missing}")
    return PublicationConfig(
        project_name=str(raw["project_name"]),
        # Trailing slashes would double up when joined with relative paths.
        canonical_base_url=str(raw["canonical_base_url"]).rstrip("/"),
        repository_url=str(raw["repository_url"]).rstrip("/"),
        release_url=str(raw["release_url"]),
        agent_index_path=str(raw["agent_index_path"]).lstrip("/"),
    )
