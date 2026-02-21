"""Datadog integration — traces, metrics, and structured logging.

Maps networking concepts to Datadog:
  Person    → Service
  Convo     → Trace
  Utterance → Span
  Face rec  → External service span
  Memory    → Database span

Metrics are sent directly via Datadog HTTP API (no dd-agent required).
Traces use ddtrace if available, otherwise noop.
"""
import json
import time
import logging
import threading
import functools
from typing import Optional, Callable

import httpx

from config import DD_API_KEY, DD_SITE, DD_SERVICE, DD_ENV

logger = logging.getLogger("orbit.datadog")

# Lazy-loaded Datadog tracer
_tracer = None

# ─── Metric Buffer (batched HTTP submission) ───

_metric_buffer: list[dict] = []
_buffer_lock = threading.Lock()
_flush_interval = 10  # seconds
_flush_timer: Optional[threading.Timer] = None


def _schedule_flush():
    """Schedule the next metric flush."""
    global _flush_timer
    if _flush_timer:
        _flush_timer.cancel()
    _flush_timer = threading.Timer(_flush_interval, _flush_metrics)
    _flush_timer.daemon = True
    _flush_timer.start()


def _flush_metrics():
    """Send buffered metrics to Datadog via HTTP API."""
    global _metric_buffer
    if not DD_API_KEY:
        with _buffer_lock:
            _metric_buffer = []
        _schedule_flush()
        return

    with _buffer_lock:
        batch = _metric_buffer[:]
        _metric_buffer = []

    if not batch:
        _schedule_flush()
        return

    # Build Datadog API v2 series payload
    series = []
    for m in batch:
        series.append({
            "metric": m["metric"],
            "type": m.get("type", 0),  # 0=unspecified, 1=count, 2=rate, 3=gauge
            "points": [{"timestamp": int(m["timestamp"]), "value": m["value"]}],
            "tags": m.get("tags", []),
        })

    try:
        resp = httpx.post(
            f"https://api.{DD_SITE}/api/v2/series",
            headers={
                "DD-API-KEY": DD_API_KEY,
                "Content-Type": "application/json",
            },
            json={"series": series},
            timeout=5.0,
        )
        if resp.status_code not in (200, 202):
            logger.warning(f"Datadog metrics submit {resp.status_code}: {resp.text[:200]}")
        else:
            logger.debug(f"Flushed {len(series)} metrics to Datadog")
    except Exception as e:
        logger.warning(f"Datadog metrics flush failed: {e}")

    _schedule_flush()


def _submit_metric(metric: str, value: float, metric_type: int = 3, tags: list[str] = None):
    """Buffer a metric for batched submission.

    metric_type: 0=unspecified, 1=count, 2=rate, 3=gauge
    """
    entry = {
        "metric": metric,
        "value": value,
        "timestamp": time.time(),
        "type": metric_type,
        "tags": (tags or []) + [f"env:{DD_ENV}", f"service:{DD_SERVICE}"],
    }
    with _buffer_lock:
        _metric_buffer.append(entry)

    # Start flush timer on first metric
    global _flush_timer
    if _flush_timer is None:
        _schedule_flush()


# ─── Log Submission (HTTP API) ───

_log_buffer: list[dict] = []
_log_lock = threading.Lock()


def _flush_logs():
    """Send buffered logs to Datadog via HTTP API."""
    global _log_buffer
    if not DD_API_KEY:
        with _log_lock:
            _log_buffer = []
        return

    with _log_lock:
        batch = _log_buffer[:]
        _log_buffer = []

    if not batch:
        return

    try:
        resp = httpx.post(
            f"https://http-intake.logs.{DD_SITE}/api/v2/logs",
            headers={
                "DD-API-KEY": DD_API_KEY,
                "Content-Type": "application/json",
            },
            json=batch,
            timeout=5.0,
        )
        if resp.status_code not in (200, 202):
            logger.warning(f"Datadog logs submit {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"Datadog logs flush failed: {e}")


def _submit_log(message: str, attributes: dict = None):
    """Buffer a structured log for submission."""
    entry = {
        "ddsource": "orbit",
        "ddtags": f"env:{DD_ENV},service:{DD_SERVICE}",
        "hostname": "orbit-backend",
        "service": DD_SERVICE,
        "message": message,
    }
    if attributes:
        entry.update(attributes)

    with _log_lock:
        _log_buffer.append(entry)

    # Flush logs every time (they're important for demo)
    threading.Thread(target=_flush_logs, daemon=True).start()


# ─── Tracing (ddtrace if available, else noop) ───

def _get_tracer():
    global _tracer
    if _tracer is None:
        try:
            from ddtrace import tracer
            _tracer = tracer
            logger.info("Datadog tracer initialized")
        except Exception as e:
            logger.info(f"ddtrace not available (using noop): {e}")
            _tracer = _NoopTracer()
    return _tracer


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
    """Record a face recognition span + metric."""
    tracer = _get_tracer()
    with tracer.trace("face.recognition", service="rekognition", resource="search_face") as span:
        span.set_tag("person.id", person_id)
        span.set_tag("face.confidence", confidence)
        span.set_tag("face.is_new", is_new)
        span.set_metric("face.latency_ms", latency_ms)
        span.set_tag("env", DD_ENV)

    # Also submit as metric via HTTP API
    _submit_metric("orbit.face.recognition_ms", latency_ms, tags=[f"person:{person_id}"])


def trace_memory_retrieval(person_id: str, query: str, results_count: int, latency_ms: float):
    """Record a memory retrieval span + metric."""
    tracer = _get_tracer()
    with tracer.trace("memory.retrieval", service="mem0", resource="search", span_type="sql") as span:
        span.set_tag("person.id", person_id)
        span.set_tag("memory.query", query[:100])
        span.set_metric("memory.results_count", results_count)
        span.set_metric("memory.latency_ms", latency_ms)
        span.set_tag("env", DD_ENV)

    _submit_metric("orbit.memory.retrieval_ms", latency_ms, tags=[f"person:{person_id}"])
    _submit_metric("orbit.memory.results_count", results_count, tags=[f"person:{person_id}"])


def trace_agent_response(intent: str, latency_ms: float, text_length: int):
    """Record an agent reasoning span + metric."""
    tracer = _get_tracer()
    with tracer.trace("agent.response", service=DD_SERVICE, resource=intent) as span:
        span.set_tag("agent.intent", intent)
        span.set_metric("agent.latency_ms", latency_ms)
        span.set_metric("agent.response_length", text_length)
        span.set_tag("env", DD_ENV)

    _submit_metric("orbit.agent.response_ms", latency_ms, tags=[f"intent:{intent}"])


def trace_tts(text_length: int, audio_size: int, latency_ms: float):
    """Record a TTS synthesis span + metric."""
    tracer = _get_tracer()
    with tracer.trace("tts.synthesis", service="elevenlabs", resource="convert") as span:
        span.set_metric("tts.text_length", text_length)
        span.set_metric("tts.audio_bytes", audio_size)
        span.set_metric("tts.latency_ms", latency_ms)
        span.set_tag("env", DD_ENV)

    _submit_metric("orbit.tts.latency_ms", latency_ms)


# ─── Custom Metrics (Self-Learning) — sent via HTTP API ───

def gauge_face_confidence(person_id: str, confidence: float):
    """Self-learning metric: face confidence per person (should trend UP)."""
    _submit_metric("orbit.face.confidence", confidence, tags=[f"person:{person_id}"])


def gauge_memory_retrieval_score(score: float):
    """Self-learning metric: memory retrieval quality 1-10 (should trend UP)."""
    _submit_metric("orbit.memory.retrieval_score", score)


def gauge_routing_accuracy(accuracy: float):
    """Self-learning metric: intent routing accuracy 0-1 (should trend UP)."""
    _submit_metric("orbit.routing.accuracy", accuracy)


def increment_interaction():
    """Counter: total interactions."""
    _submit_metric("orbit.interactions.count", 1, metric_type=1)  # type=1 is count


def increment_person_identified():
    """Counter: new people identified."""
    _submit_metric("orbit.people.identified", 1, metric_type=1)


def gauge_pipeline_latency(stage: str, latency_ms: float):
    """Track latency of each pipeline stage."""
    _submit_metric(f"orbit.pipeline.{stage}_ms", latency_ms)


def log_interaction(person_id: str, intent: str, confidence: float, memories_found: int, response_text: str):
    """Structured log line — sent to both Python logger and Datadog Logs API."""
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
    # Local log
    logger.info(json.dumps(log_entry))

    # Send to Datadog Logs API
    _submit_log(
        f"[{intent}] {person_id} (conf={confidence:.0f}%, mem={memories_found}) → {response_text[:80]}",
        attributes=log_entry,
    )


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
        {
            "definition": {
                "title": "Pipeline Latency",
                "type": "timeseries",
                "requests": [
                    {"q": f"avg:orbit.pipeline.face_pipeline_ms{{env:{DD_ENV}}}", "display_type": "line"},
                    {"q": f"avg:orbit.pipeline.memory_retrieval_ms{{env:{DD_ENV}}}", "display_type": "line"},
                    {"q": f"avg:orbit.pipeline.agent_response_ms{{env:{DD_ENV}}}", "display_type": "line"},
                    {"q": f"avg:orbit.pipeline.tts_ms{{env:{DD_ENV}}}", "display_type": "line"},
                ],
            }
        },
    ],
}


# ─── Noop Fallbacks (for when ddtrace isn't installed) ───

class _NoopSpan:
    def set_tag(self, *a, **kw): pass
    def set_metric(self, *a, **kw): pass
    def finish(self): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass

class _NoopTracer:
    def trace(self, *a, **kw): return _NoopSpan()
    def configure(self, **kw): pass
