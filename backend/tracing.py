"""Distributed tracing setup (OpenTelemetry). Spans are always created (so
trace context/IDs exist for correlation), but are only *exported* somewhere
if explicitly configured: set OTEL_EXPORTER_OTLP_ENDPOINT to ship spans to a
real collector (Jaeger/Tempo/Grafana/Honeycomb/etc.), or FIN_OTEL_CONSOLE=true
for verbose local debugging. Neither set = spans exist but aren't printed,
keeping logs readable.
"""
import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from backend.config import OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_SERVICE_NAME

_configured = False


def configure_tracing() -> None:
    global _configured
    if _configured:
        return

    provider = TracerProvider(resource=Resource.create({"service.name": OTEL_SERVICE_NAME}))

    if OTEL_EXPORTER_OTLP_ENDPOINT:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        exporter = OTLPSpanExporter(endpoint=f"{OTEL_EXPORTER_OTLP_ENDPOINT}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
    elif os.environ.get("FIN_OTEL_CONSOLE", "").lower() == "true":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    # else: no exporter attached - spans are created (usable for future
    # instrumentation) but nothing is printed or shipped anywhere.

    trace.set_tracer_provider(provider)
    _configured = True


def get_tracer(name: str):
    return trace.get_tracer(name)
