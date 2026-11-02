"""Official OTel SDK for the ERP application's native event boundaries.

Only opt-in exporter configuration enables remote traces. Never logs payloads,
headers, SQL, credentials, human/tenant identifiers or exception messages.
Telemetry cannot replace IAM/CP authority or ERP posting vetoes.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

from opentelemetry import context, propagation, trace
from opentelemetry.trace import Link, SpanKind, Status, StatusCode
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

_provider: TracerProvider | None = None


def configure() -> None:
    """Idempotent, explicit exporter setup for the running ERP application."""
    global _provider
    if _provider is not None:
        return
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if not endpoint:
        return
    environment = os.environ.get("BAOBAB_ENVIRONMENT", "development")
    target = urlsplit(endpoint)
    if target.scheme not in ("http", "https") or target.username or target.password or target.query or target.fragment or (
            target.path != "/v1/traces") or (environment not in ("development", "test", "integration") and target.scheme != "https"):
        raise RuntimeError("ERP_OTLP_ENDPOINT_NOT_APPROVED")
    provider = TracerProvider(resource=Resource.create({
        "service.name": "baobab-erp",
        "service.namespace": "baobab",
        "service.version": os.environ.get("BAOBAB_SERVICE_VERSION", "development"),
        "deployment.environment.name": environment,
    }))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, timeout=6)))
    trace.set_tracer_provider(provider)
    _provider = provider


def consumer_span(traceparent: str | None, name: str):
    """Native consumer span with an explicit link to *verified* CloudEvent origin.

    A message may be retried in a new process/trace; parentage must NOT be
    inferred merely by copying an untrusted incoming traceparent as authority.
    """
    links = []
    remote_context = None
    if traceparent:
        candidate = propagation.extract({"traceparent": traceparent})
        context_span = trace.get_current_span(candidate).get_span_context()
        if context_span.is_valid:
            remote_context = candidate
            links.append(Link(context_span))
    # A *signed and schema-validated* CloudEvent may carry causal parent
    # context. Event authentication happens BEFORE the caller opens this
    # span; neither it nor this trace context supplies an ERP grant.
    return trace.get_tracer("baobab.erp.native", "dev11").start_as_current_span(
        name, context=remote_context, kind=SpanKind.CONSUMER, links=links)


def diagnostic_outcome(span, code: str, *, failed: bool = False):
    """Closed, low-cardinality outcome; no arbitrary user-controlled exception."""
    allowed = {"ADMITTED", "DUPLICATE", "REJECTED_SIGNATURE", "REJECTED_CONTRACT",
               "DB_RETRY", "BUSINESS_PROCESSED", "BUSINESS_BLOCKED", "BUSINESS_RETRY",
               "BUSINESS_DEAD_LETTER"}
    if code not in allowed:
        raise ValueError("ERP_OTEL_OUTCOME_NOT_ALLOWLISTED")
    span.set_attribute("baobab.erp.event_outcome", code)
    if failed:
        span.set_status(Status(StatusCode.ERROR))


def shutdown() -> None:
    """Flush native spans before the disposable consumer process exits."""
    global _provider
    provider = _provider
    if provider is not None:
        provider.force_flush(timeout_millis=20000)
        provider.shutdown()
        _provider = None
