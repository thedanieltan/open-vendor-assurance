# Minimal OCI image for the read-only OpenVA MCP server.
# Build from the repository root so the local adapter packages are available:
#   docker build -f integrations/mcp/openva_mcp/Dockerfile -t openva-mcp .
FROM python:3.12-slim

ARG SOURCE_COMMIT=unknown
LABEL org.opencontainers.image.title="openva-mcp" \
      org.opencontainers.image.description="Read-only MCP server over the OpenVA public export contract." \
      org.opencontainers.image.source="https://github.com/thedanieltan/open-vendor-assurance" \
      org.opencontainers.image.revision="${SOURCE_COMMIT}" \
      org.opencontainers.image.licenses="MIT" \
      io.modelcontextprotocol.server.name="io.github.thedanieltan/openva"

WORKDIR /app
# The MCP server reuses the shared matching core, so its local dependency chain
# (pack reader -> inventory matcher) is installed alongside it. None are on PyPI
# yet; installing from local paths keeps the image self-contained.
COPY adapters/python/openva_pack_reader ./openva_pack_reader
COPY adapters/python/openva_vendor_inventory_matcher ./openva_vendor_inventory_matcher
COPY integrations/mcp/openva_mcp ./openva_mcp
RUN pip install --no-cache-dir ./openva_pack_reader ./openva_vendor_inventory_matcher ./openva_mcp

# Run as an unprivileged user; the application directory is not written to at
# runtime. The MCP tool surface has no catalog-write authority and needs no
# secrets or network listener: it speaks stdio only.
RUN useradd --create-home --uid 10001 openva
USER openva

# Pinned-local mode: mount a snapshot read-only at /snapshot.
#   docker run --rm -i --read-only -v /path/to/export:/snapshot:ro openva-mcp
# Hosted mode with caching: also mount a writable cache and pass
#   --base-url <url> --cache-dir /cache  (mount -v cache:/cache).
ENV OPENVA_SNAPSHOT_DIR=/snapshot
ENTRYPOINT ["openva-mcp"]
CMD ["--snapshot", "/snapshot"]
