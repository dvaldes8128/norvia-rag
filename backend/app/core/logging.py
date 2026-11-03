"""Structured logging with a correlation id (Q6).

structlog renders JSON log lines. A correlation id is kept in a ``contextvars`` slot so
every log line emitted while handling a request — or running a Celery task — carries the
same ``correlation_id``. The id is read from the incoming ``X-Request-ID`` header (or a
fresh UUID), echoed back on the response, and propagated into the Celery task as an
explicit kwarg so API and worker logs for one operation share it.

Redaction (Q6.2): we never log full document content nor full user questions. Use
:func:`redacted_text` to log only length + a short sha256 prefix + a truncated preview.
"""

from __future__ import annotations

import hashlib
import logging
import sys
import uuid
from contextvars import ContextVar

import structlog

# Mirror of the structlog contextvar for cheap, framework-agnostic reads (e.g. Celery).
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

_configured = False


def setup_logging(level: str | None = None) -> None:
    """Configure structlog + stdlib logging to emit JSON lines. Idempotent."""
    global _configured

    log_level = getattr(logging, (level or "INFO").upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
        force=True,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=False,
    )
    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger (configuring lazily if needed)."""
    if not _configured:
        setup_logging()
    return structlog.get_logger(name)


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def bind_correlation_id(correlation_id: str) -> str:
    """Bind ``correlation_id`` to the current context so logs include it."""
    _correlation_id.set(correlation_id)
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
    return correlation_id


def get_correlation_id() -> str | None:
    """Return the correlation id bound to the current context, if any."""
    return _correlation_id.get()


def clear_correlation() -> None:
    """Clear context-local bindings (called at the start of each request/task)."""
    _correlation_id.set(None)
    structlog.contextvars.clear_contextvars()


def redacted_text(field: str, text: str, *, preview_chars: int = 32) -> dict[str, object]:
    """Return redaction-safe fields describing ``text`` without dumping it in full.

    Produces ``{field}_len``, ``{field}_sha256`` (8-char prefix) and ``{field}_preview``
    (first N chars) so logs stay useful for debugging without leaking full document
    content or user questions (Q6.2).
    """
    data = (text or "").encode("utf-8")
    return {
        f"{field}_len": len(text or ""),
        f"{field}_sha256": hashlib.sha256(data).hexdigest()[:8],
        f"{field}_preview": (text or "")[:preview_chars],
    }
