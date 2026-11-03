"""SQLAlchemy engine, session factory and declarative base."""

from __future__ import annotations

from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)

# Emit a span per DB statement so query spans appear as children of the API/Celery span
# (Q3). Instrumenting the engine keeps this independent of how sessions are opened.
SQLAlchemyInstrumentor().instrument(engine=engine)


class Base(DeclarativeBase):
    pass
