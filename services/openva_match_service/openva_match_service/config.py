from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

SERVICE_VERSION = "0.1.0"
ADVISORY_BOUNDARY = "non_advisory"


@dataclass(frozen=True)
class ServiceConfig:
    pack_path: Path
    api_key: str
    service_version: str = SERVICE_VERSION

    @classmethod
    def from_env(cls) -> "ServiceConfig":
        pack_path = os.environ.get("OPENVA_PACK_PATH", "").strip()
        api_key = os.environ.get("OPENVA_SERVICE_API_KEY", "").strip()
        if not pack_path:
            raise RuntimeError("OPENVA_PACK_PATH is required")
        if not api_key:
            raise RuntimeError("OPENVA_SERVICE_API_KEY is required")
        return cls(pack_path=Path(pack_path), api_key=api_key)
