"""ASGI middleware that establishes a per-request correlation id (Q6).

Reads an incoming ``X-Request-ID`` (or generates a UUID), binds it so every structlog
line in the request carries ``correlation_id``, tags the active OpenTelemetry span with
it, and echoes it back on the response ``X-Request-ID`` header.
"""

from __future__ import annotations

from opentelemetry import trace
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import bind_correlation_id, clear_correlation, new_correlation_id

_HEADER = "x-request-id"


class CorrelationIdMiddleware:
    """Pure ASGI middleware; cheaper than ``BaseHTTPMiddleware`` and stream-safe."""

    def __init__(self, app: ASGIApp, header_name: str = _HEADER) -> None:
        self.app = app
        self.header_name = header_name.lower()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        correlation_id = headers.get(self.header_name) or new_correlation_id()

        clear_correlation()
        bind_correlation_id(correlation_id)

        span = trace.get_current_span()
        if span is not None and span.get_span_context().is_valid:
            span.set_attribute("correlation_id", correlation_id)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[self.header_name] = correlation_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            clear_correlation()
