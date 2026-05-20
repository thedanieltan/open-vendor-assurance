#!/usr/bin/env sh
set -eu

: "${OPENVA_SERVICE_URL:=http://localhost:8000}"
: "${OPENVA_SERVICE_API_KEY:?OPENVA_SERVICE_API_KEY is required}"
export OPENVA_SERVICE_URL
export OPENVA_SERVICE_API_KEY

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

if command -v curl >/dev/null 2>&1; then
  curl -fsS \
    -H "Authorization: Bearer ${OPENVA_SERVICE_API_KEY}" \
    -F "inventory_csv=@${SCRIPT_DIR}/sample_inventory.csv;type=text/csv" \
    "${OPENVA_SERVICE_URL}/match" \
    | python -m json.tool
else
  export SAMPLE_INVENTORY_PATH="${SCRIPT_DIR}/sample_inventory.csv"
  python - <<'PY'
import json
import os
import uuid
import urllib.request

boundary = "openva-" + uuid.uuid4().hex
with open(os.environ["SAMPLE_INVENTORY_PATH"], "rb") as inventory:
    csv_bytes = inventory.read()

body = b"".join(
    [
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="inventory_csv"; filename="sample_inventory.csv"\r\n',
        b"Content-Type: text/csv\r\n\r\n",
        csv_bytes,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
)

request = urllib.request.Request(
    os.environ["OPENVA_SERVICE_URL"].rstrip("/") + "/match",
    data=body,
    headers={
        "Authorization": f"Bearer {os.environ['OPENVA_SERVICE_API_KEY']}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    },
    method="POST",
)
with urllib.request.urlopen(request) as response:
    print(json.dumps(json.load(response), indent=4, sort_keys=True))
PY
fi
