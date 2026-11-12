"""Structured observability: JSON logging, tracing, call instrumentation, PII redaction.

`instrument` wraps `agent/tools/*` functions -- the boundary this project actually
controls. Agent Engine's managed runtime drives the ADK `Runner` internally, so a
decorator on `Runner.run_async` would never fire in production; tool calls are invoked
by our own code regardless of where the agent runs.

Logs go to stdout and need no client library; traces need an exporter and two
environment variables. "Observability" in AGENTS.md explains why, and is the first
place to look when logs or spans appear to be missing.

Telemetry must never break a tool call: if a library is missing or credentials cannot be
resolved, the failure is reported once on stderr and the tool runs on.
"""

from __future__ import annotations

import atexit
import functools
import inspect
import json
import logging
import os
import re
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, TypeVar

SERVICE_NAME = "{{cookiecutter.project_slug}}"

_TRUTHY = frozenset({"1", "true", "yes", "on"})

F = TypeVar("F", bound=Callable[..., Any])

# Best-effort patterns for common PII shapes. Not exhaustive -- a defence in depth
# measure for logs, not a substitute for not logging sensitive fields in the first place.
_PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[REDACTED_EMAIL]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    (re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"), "[REDACTED_CARD]"),
]


def _env_flag(name: str) -> bool:
    """Read a boolean environment variable. Absent or unrecognised means off."""
    return os.getenv(name, "").strip().lower() in _TRUTHY


def _warn(message: str) -> None:
    """Report a telemetry setup failure without going through `logger`.

    Writes straight to stderr: this runs while `logger` is still being assembled,
    and routing it through the logger being configured risks recursion.
    """
    sys.stderr.write(f"observability: {message}\n")


def _stdout_handler() -> logging.Handler:
    """Handler writing raw JSON lines to stdout -- the local and eval-time destination."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    return handler


def _build_tracer() -> Any:
    """Configure an OpenTelemetry tracer exporting to Cloud Trace, or return None.

    Returns None -- disabling span emission entirely -- when `CLOUD_TRACE_ENABLED`
    is off, the exporter is not installed, or the provider cannot be built.
    """
    if not _env_flag("CLOUD_TRACE_ENABLED"):
        return None
    try:
        from opentelemetry import trace  # noqa: PLC0415
        from opentelemetry.exporter.cloud_trace import (  # noqa: PLC0415
            CloudTraceSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource  # noqa: PLC0415
        from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
        from opentelemetry.sdk.trace.export import (  # noqa: PLC0415
            BatchSpanProcessor,
        )

        provider = TracerProvider(
            resource=Resource.create({"service.name": SERVICE_NAME})
        )
        provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter()))
        trace.set_tracer_provider(provider)
        # BatchSpanProcessor buffers; without this, spans from a short-lived
        # process are dropped before they are ever exported.
        atexit.register(provider.shutdown)
        return trace.get_tracer(SERVICE_NAME)
    except Exception as exc:
        _warn(f"Cloud Trace exporter unavailable, spans disabled: {exc}")
        return None


logger = logging.getLogger("{{cookiecutter.project_slug}}.observability")
if not logger.handlers:
    logger.addHandler(_stdout_handler())
    logger.setLevel(logging.INFO)
    logger.propagate = False

_TRACER = _build_tracer()


@contextmanager
def _span(name: str) -> Iterator[Any]:
    """Enter a Cloud Trace span, or yield None when tracing is not configured."""
    if _TRACER is None:
        yield None
        return
    with _TRACER.start_as_current_span(name) as span:
        yield span


def _record_span_error(span: Any, exc: Exception) -> None:
    """Mark a span as failed. Best-effort: telemetry must not mask the real exception."""
    if span is None:
        return
    try:
        from opentelemetry.trace import Status, StatusCode  # noqa: PLC0415

        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, str(exc)))
    except Exception as span_exc:
        _warn(f"could not record exception on span: {span_exc}")


def _set_span_error_status(span: Any, message: str) -> None:
    """Mark a span as failed without an exception, for a tool that returned an error."""
    if span is None:
        return
    try:
        from opentelemetry.trace import Status, StatusCode  # noqa: PLC0415

        span.set_status(Status(StatusCode.ERROR, message))
    except Exception as span_exc:
        _warn(f"could not set error status on span: {span_exc}")


# Longest error text an error-shaped result contributes to a log line or span status.
_MAX_ERROR_TEXT = 500


def _result_error(result: Any) -> str | None:
    """The error text of an error-shaped tool result, or None for a normal result.

    Tools return errors to the model instead of raising, so the model can explain them
    and the turn does not fail. Without this, such a call would be logged as a success.
    Recognised shapes:

    - a string starting with "ERROR" (e.g. "ERROR: table not found");
    - a dict with a truthy "error" key, or with "status" == "error" (ADK's documented
      tool convention, with the text in "error_message");
    - any other object with a truthy `error` attribute (e.g. a Pydantic response model).
    """
    error: Any = None
    if isinstance(result, str):
        if result.startswith("ERROR"):
            error = result
    elif isinstance(result, dict):
        if result.get("error"):
            error = result["error"]
        elif result.get("status") == "error":
            error = result.get("error_message") or "status: error"
    elif not isinstance(result, (list, tuple, set, bytes, int, float, bool)):
        attribute = getattr(result, "error", None)
        if attribute and not callable(attribute):
            error = attribute
    if not error:
        return None
    return str(error)[:_MAX_ERROR_TEXT]


def _set_span_attribute(span: Any, key: str, value: Any) -> None:
    """Set one span attribute, best-effort, for the same reason as `_record_span_error`."""
    if span is None:
        return
    try:
        span.set_attribute(key, value)
    except Exception as span_exc:
        _warn(f"could not set span attribute {key!r}: {span_exc}")


def redact_pii(value: Any) -> Any:
    """Redact emails, SSNs, and credit-card-shaped numbers from a value.

    Recurses into dicts, lists, and tuples; strings are scanned in place; any
    other type passes through unchanged.
    """
    if isinstance(value, str):
        redacted = value
        for pattern, placeholder in _PII_PATTERNS:
            redacted = pattern.sub(placeholder, redacted)
        return redacted
    if isinstance(value, dict):
        return {key: redact_pii(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_pii(item) for item in value]
    return value


def log_event(
    event_type: str, fields: dict[str, Any] | None = None, severity: str = "INFO"
) -> None:
    """Emit one structured JSON log line to every configured destination.

    The line is a JSON object printed to stdout. Cloud Logging parses a JSON stdout
    line into a `jsonPayload` when Agent Engine forwards it, so these fields stay
    queryable as structured data rather than as text. `severity` is carried in the
    payload and also drives the Python log level. Note that entries arriving this way
    take their LogEntry severity from the payload's `severity` key, not from the log
    level -- which is why it is written into the payload rather than left implicit.
    All other field values are passed through `redact_pii` first.
    """
    payload: dict[str, Any] = {
        "severity": severity,
        "agent_name": "root_agent",
        "event": event_type,
    }
    payload.update(redact_pii(fields or {}))
    log = logger.error if severity == "ERROR" else logger.info
    log(json.dumps(payload, default=str))


def log_model_usage(event: Any) -> None:
    """Log token counts from an ADK event's `usage_metadata`, if present.

    Only reachable in code that iterates the event stream itself (e.g. the
    promptfoo eval provider) -- Agent Engine's own request path never runs
    this, since its managed runtime drives the Runner internally.
    """
    try:
        usage = getattr(event, "usage_metadata", None)
        if usage is None:
            return
        log_event(
            "model.usage",
            {
                "prompt_tokens": getattr(usage, "prompt_token_count", None),
                "candidates_tokens": getattr(usage, "candidates_token_count", None),
                "total_tokens": getattr(usage, "total_token_count", None),
            },
        )
    except Exception:
        logger.debug("Could not extract usage metadata from event", exc_info=True)


def instrument(func: F) -> F:
    """Log and trace name, (redacted) arguments, outcome, and duration for every call.

    Works on sync or async callables. Emits `<name>.start` / `.end` / `.error` log
    events and, when tracing is configured, wraps the call in a Cloud Trace span
    named after the function. A raised exception gives `.error`; a returned
    error-shaped result (see `_result_error`) gives `.end` with `outcome: "error"` at
    ERROR severity and is returned unchanged. `functools.wraps` keeps the wrapped function's name,
    docstring, and signature intact via `__wrapped__`, so ADK's tool-schema
    introspection sees the original function unchanged.
    """

    def _start(args: tuple[Any, ...], kwargs: dict[str, Any]) -> float:
        log_event(f"{func.__name__}.start", {"args": args, "kwargs": kwargs})
        return time.perf_counter()

    def _end(start: float, span: Any, result: Any) -> None:
        duration_ms = (time.perf_counter() - start) * 1000
        _set_span_attribute(span, "duration_ms", round(duration_ms, 2))
        error = _result_error(result)
        if error is None:
            _set_span_attribute(span, "outcome", "success")
            log_event(
                f"{func.__name__}.end",
                {"duration_ms": round(duration_ms, 2), "outcome": "success"},
            )
            return
        # The tool returned an error instead of raising: still a failed call.
        _set_span_attribute(span, "outcome", "error")
        _set_span_error_status(span, error)
        log_event(
            f"{func.__name__}.end",
            {"duration_ms": round(duration_ms, 2), "outcome": "error", "error": error},
            severity="ERROR",
        )

    def _error(start: float, exc: Exception, span: Any) -> None:
        duration_ms = (time.perf_counter() - start) * 1000
        _set_span_attribute(span, "outcome", "error")
        _set_span_attribute(span, "duration_ms", round(duration_ms, 2))
        _record_span_error(span, exc)
        log_event(
            f"{func.__name__}.error",
            {"duration_ms": round(duration_ms, 2), "error": str(exc)},
            severity="ERROR",
        )

    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
            with _span(func.__name__) as span:
                start = _start(args, kwargs)
                try:
                    result = await func(*args, **kwargs)
                except Exception as exc:
                    _error(start, exc, span)
                    raise
                _end(start, span, result)
                return result

        return _async_wrapper  # type: ignore[return-value]

    @functools.wraps(func)
    def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        with _span(func.__name__) as span:
            start = _start(args, kwargs)
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                _error(start, exc, span)
                raise
            _end(start, span, result)
            return result

    return _sync_wrapper  # type: ignore[return-value]
