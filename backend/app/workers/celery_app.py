"""Celery application. Ingestion tasks are registered under app.workers.tasks."""

from __future__ import annotations

from celery import Celery
from celery.signals import worker_process_init
from opentelemetry.instrumentation.celery import CeleryInstrumentor

from app.config import settings
from app.core.logging import setup_logging
from app.core.telemetry import setup_telemetry

celery = Celery(
    "norvia",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
)

# Instrument at import time so BOTH sides participate: the API (producer) injects the
# trace context into the task message on publish, and the worker (consumer) extracts it.
# This is what makes worker spans children of the API span across the Redis broker (Q3).
CeleryInstrumentor().instrument()


@worker_process_init.connect(weak=False)
def _init_worker_observability(**_kwargs: object) -> None:
    """Configure logging + a TracerProvider once per worker process (Q3 / Q6)."""
    setup_logging(settings.log_level)
    setup_telemetry(settings.otel_service_name)
