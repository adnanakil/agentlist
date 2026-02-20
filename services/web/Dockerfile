FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY packages/ag-common/ packages/ag-common/
COPY packages/ag-db/ packages/ag-db/
COPY services/web/ services/web/

RUN pip install --no-cache-dir \
    ./packages/ag-common \
    ./packages/ag-db \
    ./services/web

WORKDIR /app/services/web

ENV PORT=8004

CMD uvicorn web.main:app --host 0.0.0.0 --port $PORT
