FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy workspace root config
COPY pyproject.toml ./

# Copy shared packages
COPY packages/ag-common/ packages/ag-common/
COPY packages/ag-db/ packages/ag-db/

# Copy this service
COPY services/gateway/ services/gateway/

# Install dependencies
RUN uv pip install --system --no-cache \
    ./packages/ag-common \
    ./packages/ag-db \
    ./services/gateway

WORKDIR /app/services/gateway

EXPOSE 8000

CMD ["uvicorn", "gateway.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
