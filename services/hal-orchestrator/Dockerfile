FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY packages/ag-common/ packages/ag-common/
COPY packages/ag-db/ packages/ag-db/
COPY services/hal-orchestrator/ services/hal-orchestrator/

RUN pip install --no-cache-dir \
    ./packages/ag-common \
    ./packages/ag-db \
    ./services/hal-orchestrator

WORKDIR /app/services/hal-orchestrator

ENV PORT=8005

CMD cd /app/packages/ag-db && alembic upgrade head && cd /app/services/hal-orchestrator && uvicorn hal_orchestrator.main:app --host 0.0.0.0 --port $PORT
