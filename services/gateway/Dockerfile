FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
WORKDIR /app

# Copy shared packages and service
COPY packages/ag-common/ packages/ag-common/
COPY packages/ag-db/ packages/ag-db/
COPY services/gateway/ services/gateway/

# Install dependencies
RUN pip install --no-cache-dir \
    ./packages/ag-common \
    ./packages/ag-db \
    ./services/gateway

WORKDIR /app/services/gateway

ENV PORT=8000

CMD uvicorn gateway.main:app --host 0.0.0.0 --port $PORT
