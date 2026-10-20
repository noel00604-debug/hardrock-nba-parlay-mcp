# Hosted MCP server image for hardrock-nba-parlay-mcp.
# Build context is the repository root:  docker build -f deploy/Dockerfile -t hrnba .
# Runtime configuration comes from HRNBA_* environment variables (see .env.example).
# The image never contains secrets; pass them at run time.

FROM python:3.12-slim AS runtime

# uv, pinned to the version used for the lockfile on the development machine (uv 0.13.1).
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# poppler-utils provides pdftotext, used to read the official NBA injury report PDF.
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependency layer first so source edits do not reinstall packages.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

# Non-root runtime user; /data holds the SQLite fallback and any local files.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin hrnba \
    && mkdir -p /data \
    && chown -R hrnba:hrnba /app /data
USER hrnba

ENV PATH="/app/.venv/bin:${PATH}" \
    HRNBA_HOST=0.0.0.0 \
    HRNBA_PORT=8080 \
    HRNBA_DATA_DIR=/data \
    HRNBA_LOG_LEVEL=INFO

EXPOSE 8080

# Streamable HTTP MCP at /mcp plus /login, /signup, /account, /healthz.
# Postgres is selected by HRNBA_DATABASE_URL; without it the server falls back to SQLite
# under /data, which is NOT durable on Railway or Fly unless a volume is mounted there.
CMD ["hrnba", "serve", "--transport", "http", "--host", "0.0.0.0", "--port", "8080"]
