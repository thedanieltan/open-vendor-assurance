from __future__ import annotations

import os

import uvicorn


def main() -> int:
    port = int(os.environ.get("OPENVA_SERVICE_PORT", "8000"))
    uvicorn.run("openva_match_service.app:create_app", factory=True, host="0.0.0.0", port=port)
    return 0
