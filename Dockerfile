# rag-crucible service image: runs the API (`crucible serve`) or the worker
# (`crucible worker`) — docker-compose picks the command per service.
#
# Default build ships the base deps only (fake provider works out of the box,
# image stays small). Build with the local models baked in:
#   docker build --build-arg WITH_LOCAL=1 -t rag-crucible:local .

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_PYTHON_PREFERENCE=only-system \
    CRUCIBLE_ARTIFACTS_DIR=/data/artifacts \
    CRUCIBLE_DB=/data/artifacts/crucible.db

WORKDIR /app
ARG WITH_LOCAL=0

# dependency layer (cached until the lockfile changes)
COPY pyproject.toml uv.lock ./
RUN if [ "$WITH_LOCAL" = "1" ]; then \
        uv sync --frozen --no-dev --no-install-project --extra local; \
    else \
        uv sync --frozen --no-dev --no-install-project; \
    fi

# project layer
COPY crucible/ crucible/
COPY api/ api/
COPY specs/ specs/
COPY datasets/ datasets/
COPY README.md ./
RUN if [ "$WITH_LOCAL" = "1" ]; then \
        uv sync --frozen --no-dev --extra local; \
    else \
        uv sync --frozen --no-dev; \
    fi

RUN mkdir -p /data/artifacts
VOLUME /data/artifacts

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "crucible", "serve", "--host", "0.0.0.0", "--port", "8000"]
