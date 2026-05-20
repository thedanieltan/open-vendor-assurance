#!/usr/bin/env sh
set -eu

: "${OPENVA_SERVICE_URL:=http://localhost:8000}"
: "${OPENVA_SERVICE_API_KEY:?OPENVA_SERVICE_API_KEY is required}"
export OPENVA_SERVICE_URL
export OPENVA_SERVICE_API_KEY

if command -v curl >/dev/null 2>&1; then
  curl -fsS \
    -H "Authorization: Bearer ${OPENVA_SERVICE_API_KEY}" \
    "${OPENVA_SERVICE_URL}/pack/meta" \
    | python -m json.tool
else
  python - <<'PY'
import json
import os
import urllib.request

request = urllib.request.Request(
    os.environ["OPENVA_SERVICE_URL"].rstrip("/") + "/pack/meta",
    headers={"Authorization": f"Bearer {os.environ['OPENVA_SERVICE_API_KEY']}"},
)
with urllib.request.urlopen(request) as response:
    print(json.dumps(json.load(response), indent=4, sort_keys=True))
PY
fi
