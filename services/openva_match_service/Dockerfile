# Explicit Debian variant (slim-bookworm) pinned by digest. The generic `3.12-slim` tag
# has rolled to Debian 13 (trixie), which currently carries materially more high/critical
# OS CVEs; slim-bookworm's inherited high/criticals are all presently unfixable and are
# captured in services/openva_match_service/accepted-base-findings.yaml. Refresh both
# together (WP-02E).
FROM python:3.12-slim-bookworm@sha256:8a7e7cc04fd3e2bd787f7f24e22d5d119aa590d429b50c95dfe12b3abe52f48b

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV OPENVA_SERVICE_PORT=8000

WORKDIR /app

# Required at runtime:
# - OPENVA_PACK_PATH: path to the mounted OpenVA pack directory, for example /data/openva-pack
# - OPENVA_SERVICE_API_KEY: pre-shared API key for Authorization: Bearer <key>
VOLUME ["/data/openva-pack"]

COPY adapters/python/openva_pack_reader ./adapters/python/openva_pack_reader
COPY adapters/python/openva_vendor_inventory_matcher ./adapters/python/openva_vendor_inventory_matcher
COPY services/openva_match_service ./services/openva_match_service

RUN pip install --no-cache-dir \
    ./adapters/python/openva_pack_reader \
    ./adapters/python/openva_vendor_inventory_matcher \
    ./services/openva_match_service

EXPOSE 8000

ENTRYPOINT ["openva-match-service"]
