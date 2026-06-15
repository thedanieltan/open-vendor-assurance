# Minimal OCI image for the read-only OpenVA MCP server.
# Build context is this directory (integrations/mcp/openva_mcp).
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY openva_mcp ./openva_mcp
RUN pip install --no-cache-dir .

# Read-only by construction: no GitHub token, no write path. Mount a snapshot
# at /snapshot (pinned local mode) or pass --base-url for hosted mode.
ENV OPENVA_SNAPSHOT_DIR=/snapshot
ENTRYPOINT ["openva-mcp"]
CMD ["--snapshot", "/snapshot"]
