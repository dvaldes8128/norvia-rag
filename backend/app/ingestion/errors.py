"""Ingestion-specific errors.

Permanent failures (corrupt/empty PDF) must not be retried by Celery.
Transient failures (DB blip, embedding provider timeout) may be retried.
"""

from __future__ import annotations


class IngestionError(Exception):
    """Base class for ingestion failures."""


class PermanentIngestionError(IngestionError):
    """Do not retry — the input or request is invalid."""


class TransientIngestionError(IngestionError):
    """Safe to retry — temporary infrastructure/provider issue."""
