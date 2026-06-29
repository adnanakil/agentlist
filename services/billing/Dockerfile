FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY packages/ag-common/ packages/ag-common/
COPY packages/ag-db/ packages/ag-db/
COPY services/billing/ services/billing/

RUN pip install --no-cache-dir \
    ./packages/ag-common \
    ./packages/ag-db \
    ./services/billing

WORKDIR /app/services/billing

ENV PORT=8002

CMD uvicorn billing.main:app --host 0.0.0.0 --port $PORT
