FROM ghcr.io/astral-sh/uv:0.12.15 AS uvbin
FROM python:3.12-slim AS builder
COPY --from=uvbin /uv /uvx /usr/local/bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY firstlook ./firstlook
COPY rules ./rules
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
RUN uv sync --frozen --no-dev

FROM python:3.12-slim
RUN groupadd --system --gid 10001 firstlook && useradd --system --uid 10001 --gid 10001 --home /app firstlook \
    && mkdir -p /data/uploads /var/log/firstlook \
    && chown -R firstlook:firstlook /data/uploads /var/log/firstlook
WORKDIR /app
COPY --from=builder --chown=firstlook:firstlook /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
CMD ["uvicorn", "firstlook.main:app", "--host", "0.0.0.0", "--port", "8000"]
