"""FastAPI application entrypoint.

Routers (upload, jobs, ask, auth), telemetry and structured logging are wired here
as the project grows. For now it exposes a health check so the stack boots end-to-end.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.config import settings

app = FastAPI(title="Norvia RAG", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}


# TODO: include routers
# from app.api import auth, upload, jobs, ask
# app.include_router(auth.router)
# app.include_router(upload.router)
# app.include_router(jobs.router)
# app.include_router(ask.router)
