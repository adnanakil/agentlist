FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY packages/ag-common/ packages/ag-common/
COPY packages/ag-db/ packages/ag-db/
COPY agent-sdk/python/ agent-sdk/python/
COPY agents/ agents/
COPY services/orchestrator/ services/orchestrator/

RUN pip install --no-cache-dir \
    ./packages/ag-common \
    ./packages/ag-db \
    ./agent-sdk/python \
    ./services/orchestrator

WORKDIR /app/services/orchestrator

ENV PORT=8003

CMD uvicorn orchestrator.main:app --host 0.0.0.0 --port $PORT
