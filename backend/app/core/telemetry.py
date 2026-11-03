"""OpenTelemetry bootstrap (Q3).

A single idempotent :func:`setup_telemetry` configures a ``TracerProvider`` with an
exporter chosen from settings:

* **console** (default, ``OTEL_TRACES_EXPORTER=console``) — spans are printed to stdout
  with a ``SimpleSpanProcessor`` so a local ``docker compose up`` shows the full span
  tree without extra infrastructure.
* **OTLP** — used automatically when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set; spans are
  batched to a collector.

The same provider is shared by the API process (FastAPI startup) and the Celery worker
(worker-init signal). Combined with ``FastAPIInstrumentor`` + ``CeleryInstrumentor`` +
``SQLAlchemyInstrumentor``, one trace spans API → Celery (context propagated over the
Redis broker) → DB query → LLM call.
"""

from __future__ import annotations

import threading

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

from app.config import settings

_lock = threading.Lock()
_provider: TracerProvider | None = None


def _build_processor():
    """Pick the exporter + processor from settings.

    OTLP wins whenever an endpoint is configured; otherwise we fall back to the console
    exporter (immediate, dependency-free).
    """
    endpoint = settings.otel_exporter_otlp_endpoint.strip()
    exporter_name = settings.otel_traces_exporter.strip().lower()

    if endpoint or exporter_name == "otlp":
        # Imported lazily so the console path never needs the OTLP exporter installed.
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=endpoint or None)
        return BatchSpanProcessor(exporter)

    # Console: SimpleSpanProcessor flushes each span on end so stdout shows them live.
    return SimpleSpanProcessor(ConsoleSpanExporter())


def setup_telemetry(service_name: str | None = None) -> TracerProvider:
    """Configure the global ``TracerProvider`` exactly once (idempotent).

    Safe to call from both the FastAPI startup hook and the Celery worker-init signal;
    subsequent calls return the already-configured provider without adding duplicate
    span processors.
    """
    global _provider
    with _lock:
        if _provider is not None:
            return _provider

        resource = Resource.create(
            {SERVICE_NAME: service_name or settings.otel_service_name}
        )
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(_build_processor())
        trace.set_tracer_provider(provider)
        _provider = provider
        return provider


def get_tracer(name: str) -> trace.Tracer:
    """Return a tracer; a no-op tracer is returned until ``setup_telemetry`` runs."""
    return trace.get_tracer(name)
