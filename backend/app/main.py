"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from app.api import ask, auth, jobs, uploads
from app.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.middleware import CorrelationIdMiddleware
from app.core.telemetry import setup_telemetry


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Configure structured logging + tracing before serving requests (Q3 / Q6).
    setup_logging(settings.log_level)
    setup_telemetry(settings.otel_service_name)
    get_logger("app.main").info(
        "api.startup",
        env=settings.app_env,
        otel_exporter=settings.otel_traces_exporter,
    )
    yield


app = FastAPI(title="Norvia RAG", version="0.1.0", lifespan=lifespan)
register_exception_handlers(app)

# Correlation id must wrap the app so every request (and its logs) carries one.
app.add_middleware(CorrelationIdMiddleware)
# Create the server span for each request; Celery context is propagated downstream.
FastAPIInstrumentor.instrument_app(app)

app.include_router(auth.router)
app.include_router(uploads.router)
app.include_router(jobs.router)
app.include_router(ask.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}
