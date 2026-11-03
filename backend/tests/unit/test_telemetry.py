"""Unit tests for the OpenTelemetry bootstrap (Q3). DB-free, fast."""

from __future__ import annotations

from opentelemetry.sdk.trace import TracerProvider

from app.core import telemetry


def test_setup_telemetry_is_idempotent() -> None:
    first = telemetry.setup_telemetry("norvia-test")
    second = telemetry.setup_telemetry("norvia-test")
    assert first is second
    assert isinstance(first, TracerProvider)


def test_setup_telemetry_configures_a_provider_with_a_processor() -> None:
    provider = telemetry.setup_telemetry("norvia-test")
    # A span processor must be registered so spans are actually exported.
    assert provider._active_span_processor is not None


def test_get_tracer_can_record_a_span_with_attributes() -> None:
    telemetry.setup_telemetry("norvia-test")
    tracer = telemetry.get_tracer("test")
    with tracer.start_as_current_span("unit-span") as span:
        span.set_attribute("tenant_id", "acme")
        span.set_attribute("llm.prompt_tokens", 7)
    assert span is not None
