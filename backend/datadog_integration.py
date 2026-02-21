"""Datadog integration — traces, metrics, and structured logging.

Maps networking concepts to Datadog:
  Person    → Service
  Convo     → Trace
  Utterance → Span
  Face rec  → External service span
  Memory    → Database span
"""
import json
import time
import logging
import functools
from typing import Optional, Callable

from config import DD_SERVICE, DD_ENV

logger = logging.getLogger("orbit.datadog")

# Lazy-loaded Datadog clients
_tracer = None
_statsd = None
_dd_logger = None


def _get_tracer():
    global _tracer
    if _tracer is None:
        try:
            from ddtrace import tracer
            tracer.configure(
                hostname="localhost",
                port=8126,
            )
            _tracer = tracer
            logger.info("Datadog tracer initialized")
        except Exception as e:
            logger.warning(f"Datadog tracer unavailable: {e}")
            _tracer = _NoopTracer()
    return _tracer


def _get_statsd():
    global _statsd
    if _statsd is None:
        try:
            from datadog import DogStatsd
            _statsd = DogStatsd(host="localhost", port=8125)
            logger.info("DogStatsD initialized")
        except Exception as e:
            logger.warning(f"DogStatsD unavailable: {e}")
            _statsd = _NoopStatsd()
    return _statsd


# ─── Tracing ───

def traced(operation_name: str, service: Optional[str] = None, resource: Optional[str] = None):
    """Decorator to trace a function as a Datadog span."""
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            tracer = _get_tracer()
            svc = service or DD_SERVICE
            with tracer.trace(operation_name, service=svc, resource=resource or func.__name__) as span:
                span.set_tag("env", DD_ENV)
                try:
                    result = func(*args, **kwargs)
                    span.set_tag("status", "success")
                    return result
                except Exception as e:
                    span.set_tag("status", "error")
                    span.set_tag("error.message", str(e))
                    raise
        return wrapper
    return decorator


def trace_interaction(person_id: str, intent: str):
    """Create a trace for an interaction with a person (person = service)."""
    tracer = _get_tracer()
    person_service = f"person.{person_id}"
    span = tracer.trace(
        "interaction",
        service=person_service,
        resource=intent,
    )
    span.set_tag("person.id", person_id)
    span.set_tag("interaction.intent", intent)
    span.set_tag("env", DD_ENV)
    return span


def trace_face_recognition(person_id: str, confidence: float, is_new: bool, latency_ms: float):
    """Record a face recognition span."""
    tracer = _get_tracer()
    with tracer.trace("face.recognition", service="rekognition", resource="search_face") as span:
        span.set_tag("person.id", person_id)
        span.set_tag("face.confidence", confidence)
        span.set_tag("face.is_new", is_new)
        span.set_metric("face.latency_ms", latency_ms)
        span.set_tag("env", DD_ENV)


def trace_memory_retrieval(person_id: str, query: str, results_count: int, latency_ms: float):
    """Record a memory retrieval span (database-type)."""
    tracer = _get_tracer()
    with tracer.trace("memory.retrieval", service="mem0", resource="search", span_type="sql") as span:
        span.set_tag("person.id", person_id)
        span.set_tag("memory.query", query[:100])
        span.set_metric("memory.results_count", results_count)
        span.set_metric("memory.latency_ms", latency_ms)
        span.set_tag("env", DD_ENV)


def trace_agent_response(intent: str, latency_ms: float, text_length: int):
    """Record an agent reasoning span."""
    tracer = _get_tracer()
    with tracer.trace("agent.response", service=DD_SERVICE, resource=intent) as span:
        span.set_tag("agent.intent", intent)
        span.set_metric("agent.latency_ms", latency_ms)
        span.set_metric("agent.response_length", text_length)
        span.set_tag("env", DD_ENV)


def trace_tts(text_length: int, audio_size: int, latency_ms: float):
    """Record a TTS synthesis span."""
    tracer = _get_tracer()
    with tracer.trace("tts.synthesis", service="elevenlabs", resource="convert") as span:
        span.set_metric("tts.text_length", text_length)
        span.set_metric("tts.audio_bytes", audio_size)
        span.set_metric("tts.latency_ms", latency_ms)
        span.set_tag("env", DD_ENV)


# ─── Custom Metrics (Self-Learning) ───

def gauge_face_confidence(person_id: str, confidence: float):
    """Self-learning metric: face confidence per person (should trend UP)."""
    statsd = _get_statsd()
    statsd.gauge("orbit.face.confidence", confidence, tags=[f"person:{person_id}", f"env:{DD_ENV}"])


def gauge_memory_retrieval_score(score: float):
    """Self-learning metric: memory retrieval quality 1-10 (should trend UP)."""
    statsd = _get_statsd()
    statsd.gauge("orbit.memory.retrieval_score", score, tags=[f"env:{DD_ENV}"])


def gauge_routing_accuracy(accuracy: float):
    """Self-learning metric: intent routing accuracy 0-1 (should trend UP)."""
    statsd = _get_statsd()
    statsd.gauge("orbit.routing.accuracy", accuracy, tags=[f"env:{DD_ENV}"])


def increment_interaction():
    """Counter: total interactions."""
    statsd = _get_statsd()
    statsd.increment("orbit.interactions.count", tags=[f"env:{DD_ENV}"])


def increment_person_identified():
    """Counter: new people identified."""
    statsd = _get_statsd()
    statsd.increment("orbit.people.identified", tags=[f"env:{DD_ENV}"])


def gauge_pipeline_latency(stage: str, latency_ms: float):
    """Track latency of each pipeline stage."""
    statsd = _get_statsd()
    statsd.gauge(f"orbit.pipeline.{stage}_ms", latency_ms, tags=[f"env:{DD_ENV}"])


def log_interaction(person_id: str, intent: str, confidence: float, memories_found: int, response_text: str):
    """Structured log line for the live log stream dashboard panel."""
    log_entry = {
        "timestamp": time.time(),
        "person_id": person_id,
        "intent": intent,
        "face_confidence": confidence,
        "memories_found": memories_found,
        "response_preview": response_text[:100],
        "service": DD_SERVICE,
        "env": DD_ENV,
    }
    logger.info(json.dumps(log_entry))


# ─── Dashboard Definition ───

DASHBOARD_JSON = {
    "title": "ORBIT — Networking Intelligence",
    "description": "Datadog for humans. Every person is a service, every conversation is a trace.",
    "widgets": [
        {
            "definition": {
                "title": "Service Map — People Network",
                "type": "servicemap",
                "requests": [{"service": DD_SERVICE, "env": DD_ENV}],
            }
        },
        {
            "definition": {
                "title": "Self-Learning Metrics (should all trend UP)",
                "type": "timeseries",
                "requests": [
                    {"q": f"avg:orbit.face.confidence{{env:{DD_ENV}}} by {{person}}", "display_type": "line", "style": {"palette": "warm"}},
                    {"q": f"avg:orbit.memory.retrieval_score{{env:{DD_ENV}}}", "display_type": "line", "style": {"palette": "cool"}},
                    {"q": f"avg:orbit.routing.accuracy{{env:{DD_ENV}}}", "display_type": "line", "style": {"palette": "purple"}},
                ],
            }
        },
        {
            "definition": {
                "title": "Live Interaction Stream",
                "type": "log_stream",
                "query": f"service:{DD_SERVICE}",
                "columns": ["timestamp", "person_id", "intent", "face_confidence", "memories_found"],
            }
        },
        {
            "definition": {
                "title": "Event Analytics",
                "type": "query_value",
                "requests": [
                    {"q": f"sum:orbit.interactions.count{{env:{DD_ENV}}}.as_count()"},
                    {"q": f"sum:orbit.people.identified{{env:{DD_ENV}}}.as_count()"},
                ],
            }
        },
    ],
}


# ─── Noop Fallbacks ───

class _NoopSpan:
    def set_tag(self, *a, **kw): pass
    def set_metric(self, *a, **kw): pass
    def finish(self): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass

class _NoopTracer:
    def trace(self, *a, **kw): return _NoopSpan()
    def configure(self, **kw): pass

class _NoopStatsd:
    def gauge(self, *a, **kw): pass
    def increment(self, *a, **kw): pass
    def histogram(self, *a, **kw): pass
