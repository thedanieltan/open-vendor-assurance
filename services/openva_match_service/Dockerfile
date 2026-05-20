FROM python:3.12-slim@sha256:9d3abd9fc11d06998ccdbdd93b4dd49b5ad7d67fcbbc11c016eb0eb2c2194891

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
