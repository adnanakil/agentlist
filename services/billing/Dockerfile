FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml ./
COPY packages/ag-common/ packages/ag-common/
COPY packages/ag-db/ packages/ag-db/
COPY services/billing/ services/billing/

RUN uv pip install --system --no-cache \
    ./packages/ag-common \
    ./packages/ag-db \
    ./services/billing

WORKDIR /app/services/billing

EXPOSE 8002

CMD ["uvicorn", "billing.main:app", "--host", "0.0.0.0", "--port", "8002"]
