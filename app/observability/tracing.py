from __future__ import annotations

from fastapi import FastAPI

from app.core.config import settings

_TRACING_CONFIGURED = False


def setup_tracing(app: FastAPI, *, service_name: str) -> None:
    """Enable OpenTelemetry tracing for the given FastAPI app."""
    if not settings.OTEL_ENABLED:
        return

    global _TRACING_CONFIGURED
    if _TRACING_CONFIGURED:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_NAMESPACE, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except Exception:
        # Tracing is optional; keep application startup resilient.
        return

    resource = Resource.create(
        {
            SERVICE_NAMESPACE: settings.OTEL_SERVICE_NAMESPACE,
            SERVICE_NAME: service_name,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT),
        )
    )
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="/health,/metrics")
    HTTPXClientInstrumentor().instrument()
    _TRACING_CONFIGURED = True
