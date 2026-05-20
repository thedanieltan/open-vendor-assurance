from __future__ import annotations

import uvicorn


def main() -> int:
    uvicorn.run("openva_match_service.app:create_app", factory=True, host="0.0.0.0", port=8000)
    return 0
