"""Celery worker definition (reserved for future async task processing).

For the MVP the orchestrator executes agent containers synchronously inside
the FastAPI request handler.  This module sets up the Celery app so that
background-task infrastructure is ready when needed.
"""

from celery import Celery

from ag_common.config import OrchestratorConfig

settings = OrchestratorConfig()

celery_app = Celery(
    "orchestrator",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
