"""FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI

from app.api import ask, auth, jobs, uploads
from app.config import settings
from app.core.errors import register_exception_handlers

app = FastAPI(title="Norvia RAG", version="0.1.0")
register_exception_handlers(app)

app.include_router(auth.router)
app.include_router(uploads.router)
app.include_router(jobs.router)
app.include_router(ask.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}
