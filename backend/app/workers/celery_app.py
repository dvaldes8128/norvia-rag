"""Celery application. Ingestion tasks are registered under app.workers.tasks."""

from __future__ import annotations

from celery import Celery

from app.config import settings

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
