"""Unit tests for agent/observability.py — no network, no GCP credentials required."""

import json
from contextlib import contextmanager

import pytest

from agent import observability
from agent.observability import instrument, log_event, log_model_usage, redact_pii


def test_redact_pii_masks_email():
    assert (
        redact_pii("contact me at jane@example.com") == "contact me at [REDACTED_EMAIL]"
    )


def test_redact_pii_masks_ssn():
    assert redact_pii("SSN: 123-45-6789") == "SSN: [REDACTED_SSN]"


def test_redact_pii_masks_credit_card():
    assert redact_pii("card 4111 1111 1111 1111") == "card [REDACTED_CARD]"


def test_redact_pii_recurses_into_dict_and_list():
    result = redact_pii({"emails": ["a@b.com", "no pii here"]})
    assert result == {"emails": ["[REDACTED_EMAIL]", "no pii here"]}


def test_redact_pii_passes_through_non_string():
    assert redact_pii(42) == 42
    assert redact_pii(None) is None


def test_log_event_emits_json_with_event_type(monkeypatch):
    messages = []
    monkeypatch.setattr("agent.observability.logger.info", messages.append)

    log_event("test", {"key": "value"})

    assert json.loads(messages[0]) == {
        "severity": "INFO",
        "agent_name": "root_agent",
        "event": "test",
        "key": "value",
    }


def test_log_event_uses_error_severity_and_logger_error(monkeypatch):
    info_messages = []
    error_messages = []
    monkeypatch.setattr("agent.observability.logger.info", info_messages.append)
    monkeypatch.setattr("agent.observability.logger.error", error_messages.append)

    log_event("test", {"key": "value"}, severity="ERROR")

    assert info_messages == []
    assert json.loads(error_messages[0])["severity"] == "ERROR"


def test_log_event_redacts_pii_in_fields(monkeypatch):
    messages = []
    monkeypatch.setattr("agent.observability.logger.info", messages.append)

    log_event("signup", {"email": "jane@example.com"})

    assert json.loads(messages[0])["email"] == "[REDACTED_EMAIL]"


def test_instrument_sync_function_returns_value_and_logs_start_and_end(monkeypatch):
    messages = []
    monkeypatch.setattr(
        "agent.observability.logger.info", lambda m: messages.append(json.loads(m))
    )

    @instrument
    def add(a, b):
        return a + b

    result = add(1, 2)

    assert result == 3
    assert [m["event"] for m in messages] == ["add.start", "add.end"]
    assert messages[1]["outcome"] == "success"
    assert "duration_ms" in messages[1]


def test_instrument_sync_function_logs_error_and_reraises(monkeypatch):
    messages = []
    monkeypatch.setattr(
        "agent.observability.logger.info", lambda m: messages.append(json.loads(m))
    )
    monkeypatch.setattr(
        "agent.observability.logger.error", lambda m: messages.append(json.loads(m))
    )

    @instrument
    def boom():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        boom()

    assert [m["event"] for m in messages] == ["boom.start", "boom.error"]
    assert messages[1]["error"] == "nope"
    assert messages[1]["severity"] == "ERROR"


async def test_instrument_async_function_returns_value_and_logs(monkeypatch):
    messages = []
    monkeypatch.setattr(
        "agent.observability.logger.info", lambda m: messages.append(json.loads(m))
    )

    @instrument
    async def fetch(x):
        return x * 2

    result = await fetch(5)

    assert result == 10
    assert [m["event"] for m in messages] == ["fetch.start", "fetch.end"]


def test_instrument_preserves_function_name_and_docstring():
    @instrument
    def documented():
        """A docstring."""
        return None

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "A docstring."


def test_log_model_usage_logs_token_counts(monkeypatch):
    messages = []
    monkeypatch.setattr(
        "agent.observability.logger.info", lambda m: messages.append(json.loads(m))
    )

    class FakeUsage:
        prompt_token_count = 10
        candidates_token_count = 5
        total_token_count = 15

    class FakeEvent:
        usage_metadata = FakeUsage()

    log_model_usage(FakeEvent())

    assert messages == [
        {
            "severity": "INFO",
            "agent_name": "root_agent",
            "event": "model.usage",
            "prompt_tokens": 10,
            "candidates_tokens": 5,
            "total_tokens": 15,
        }
    ]


def test_log_model_usage_noop_without_usage_metadata(monkeypatch):
    messages = []
    monkeypatch.setattr("agent.observability.logger.info", messages.append)

    class FakeEvent:
        pass

    log_model_usage(FakeEvent())

    assert messages == []


# --- Destination wiring -------------------------------------------------------
#
# Logs need no wiring: Agent Engine forwards container stdout to Cloud Logging, which
# a live deployment confirmed. Traces do, since nothing forwards spans -- and the
# exporter must stay off by default so a local `make dev` never writes to a real GCP
# project.


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " true "])
def test_env_flag_recognises_truthy_values(monkeypatch, value):
    monkeypatch.setenv("SOME_FLAG", value)

    assert observability._env_flag("SOME_FLAG") is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe"])
def test_env_flag_treats_everything_else_as_off(monkeypatch, value):
    monkeypatch.setenv("SOME_FLAG", value)

    assert observability._env_flag("SOME_FLAG") is False


def test_env_flag_absent_variable_is_off(monkeypatch):
    monkeypatch.delenv("SOME_FLAG", raising=False)

    assert observability._env_flag("SOME_FLAG") is False


def test_tracer_is_not_built_by_default(monkeypatch):
    monkeypatch.delenv("CLOUD_TRACE_ENABLED", raising=False)

    assert observability._build_tracer() is None


def test_tracer_build_failure_disables_spans_without_raising(monkeypatch, capsys):
    monkeypatch.setenv("CLOUD_TRACE_ENABLED", "true")
    monkeypatch.setattr(
        "opentelemetry.sdk.trace.TracerProvider",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no exporter")),
    )

    assert observability._build_tracer() is None
    assert "no exporter" in capsys.readouterr().err


# --- Spans --------------------------------------------------------------------


class FakeSpan:
    """Records what @instrument does to a span, without an OTel SDK."""

    def __init__(self):
        self.attributes = {}
        self.exceptions = []
        self.status = None

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def record_exception(self, exc):
        self.exceptions.append(exc)

    def set_status(self, status):
        self.status = status


class FakeTracer:
    def __init__(self):
        self.spans = {}

    @contextmanager
    def start_as_current_span(self, name):
        span = FakeSpan()
        self.spans[name] = span
        yield span


@pytest.fixture
def fake_tracer(monkeypatch):
    tracer = FakeTracer()
    monkeypatch.setattr(observability, "_TRACER", tracer)
    return tracer


def test_span_yields_none_when_tracing_is_disabled(monkeypatch):
    monkeypatch.setattr(observability, "_TRACER", None)

    with observability._span("anything") as span:
        assert span is None


def test_instrument_opens_a_span_named_after_the_function(fake_tracer):
    @instrument
    def add(a, b):
        return a + b

    assert add(1, 2) == 3
    assert "add" in fake_tracer.spans


def test_instrument_records_success_outcome_and_duration_on_the_span(fake_tracer):
    @instrument
    def add(a, b):
        return a + b

    add(1, 2)

    attributes = fake_tracer.spans["add"].attributes
    assert attributes["outcome"] == "success"
    assert "duration_ms" in attributes


def test_instrument_records_the_exception_on_the_span_and_reraises(fake_tracer):
    @instrument
    def boom():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        boom()

    span = fake_tracer.spans["boom"]
    assert span.attributes["outcome"] == "error"
    assert [str(exc) for exc in span.exceptions] == ["nope"]
    assert span.status is not None


async def test_instrument_opens_a_span_for_async_functions_too(fake_tracer):
    @instrument
    async def fetch(x):
        return x * 2

    assert await fetch(5) == 10
    assert fake_tracer.spans["fetch"].attributes["outcome"] == "success"


def test_instrument_works_unchanged_when_tracing_is_disabled(monkeypatch):
    """Spans are additive: the log events are the contract that must not regress."""
    monkeypatch.setattr(observability, "_TRACER", None)
    messages = []
    monkeypatch.setattr(
        "agent.observability.logger.info", lambda m: messages.append(json.loads(m))
    )

    @instrument
    def add(a, b):
        return a + b

    assert add(1, 2) == 3
    assert [m["event"] for m in messages] == ["add.start", "add.end"]


def test_build_tracer_returns_a_usable_tracer(monkeypatch):
    """Exercises the real OTel SDK wiring with a stand-in exporter; whether spans
    actually arrive in Cloud Trace is only provable by a deploy."""
    monkeypatch.setenv("CLOUD_TRACE_ENABLED", "true")

    class FakeExporter:
        def export(self, spans):
            return None

        def shutdown(self):
            return None

        def force_flush(self, timeout_millis=None):  # noqa: ARG002
            return True

    monkeypatch.setattr(
        "opentelemetry.exporter.cloud_trace.CloudTraceSpanExporter",
        lambda *a, **kw: FakeExporter(),
    )

    tracer = observability._build_tracer()

    assert tracer is not None
    with tracer.start_as_current_span("probe") as span:
        assert span is not None


def test_span_attribute_failure_is_reported_not_raised(capsys):
    """A broken span must not turn a working tool call into a failure."""

    class BrokenSpan:
        def set_attribute(self, key, value):
            raise RuntimeError("span is closed")

    observability._set_span_attribute(BrokenSpan(), "outcome", "success")

    assert "span is closed" in capsys.readouterr().err


def test_span_error_recording_failure_is_reported_not_raised(capsys):
    """Same reason: recording the error must never replace the original exception."""

    class BrokenSpan:
        def record_exception(self, exc):
            raise RuntimeError("span is closed")

    observability._record_span_error(BrokenSpan(), ValueError("original"))

    assert "span is closed" in capsys.readouterr().err


async def test_instrument_records_async_exception_on_the_span_and_reraises(fake_tracer):
    @instrument
    async def boom():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        await boom()

    span = fake_tracer.spans["boom"]
    assert span.attributes["outcome"] == "error"
    assert [str(exc) for exc in span.exceptions] == ["nope"]


# Tools return errors to the model instead of raising. @instrument must still record
# such a call as failed, and return the result unchanged.


class ErrorResponse:
    """Stands in for a tool's response model with an `error` field."""

    def __init__(self, error=None, rows=None):
        self.error = error
        self.rows = rows or []


@pytest.fixture
def captured_logs(monkeypatch):
    messages = []
    monkeypatch.setattr(
        "agent.observability.logger.info", lambda m: messages.append(json.loads(m))
    )
    monkeypatch.setattr(
        "agent.observability.logger.error", lambda m: messages.append(json.loads(m))
    )
    return messages


@pytest.mark.parametrize(
    ("result", "expected_error"),
    [
        ("ERROR: table not found", "ERROR: table not found"),
        ({"error": "quota exceeded"}, "quota exceeded"),
        ({"status": "error", "error_message": "no such repo"}, "no such repo"),
        ({"status": "error"}, "status: error"),
        (ErrorResponse(error="permission denied"), "permission denied"),
        (ErrorResponse(error=ValueError("bad input")), "bad input"),
        ({"error": {"code": 404}}, "{'code': 404}"),
        (ErrorResponse(error=TimeoutError()), "TimeoutError"),
    ],
    ids=[
        "error-string",
        "error-key",
        "adk-status",
        "adk-status-no-text",
        "attribute",
        "attribute-exception",
        "error-object",
        "exception-without-message",
    ],
)
def test_instrument_logs_an_error_shaped_result_as_a_failed_end(
    captured_logs, result, expected_error
):
    @instrument
    def tool():
        return result

    assert tool() is result

    assert [m["event"] for m in captured_logs] == ["tool.start", "tool.end"]
    end = captured_logs[1]
    assert end["outcome"] == "error"
    assert end["error"] == expected_error
    assert end["severity"] == "ERROR"


@pytest.mark.parametrize(
    "result",
    [
        "2026-11-12T10:00:00+00:00",
        "an error occurred earlier, but this answer is fine",
        {"error": None, "rows": [1]},
        {"error": "", "status": "success"},
        {"status": "success"},
        ErrorResponse(error=None, rows=[1]),
        ["ERROR: inside a list is data, not the tool's status"],
        42,
        None,
        "ERRORS: none found in the log",
        {"error": 0.03, "rmse": 0.03},
        ErrorResponse(error=0.12),
        {"error": True},
    ],
    ids=[
        "plain-string",
        "lowercase-error-word",
        "error-key-none",
        "error-key-empty",
        "adk-success",
        "attribute-none",
        "list",
        "int",
        "none",
        "errors-word-without-colon",
        "numeric-error-metric",
        "numeric-error-attribute",
        "boolean-error-key",
    ],
)
def test_instrument_logs_a_normal_result_as_success(captured_logs, result):
    @instrument
    def tool():
        return result

    tool()

    end = captured_logs[1]
    assert end["outcome"] == "success"
    assert "error" not in end
    assert end["severity"] == "INFO"


def test_instrument_ignores_an_error_method(captured_logs):
    """An object whose `error` is a method, not a value, is a normal result."""

    class Logger:
        def error(self, message):
            return message

    @instrument
    def tool():
        return Logger()

    tool()

    assert captured_logs[1]["outcome"] == "success"


def test_instrument_truncates_long_error_text(captured_logs):
    @instrument
    def tool():
        return "ERROR: " + "x" * 2000

    tool()

    assert len(captured_logs[1]["error"]) == observability._MAX_ERROR_TEXT


def test_instrument_redacts_pii_in_returned_error_text(captured_logs):
    @instrument
    def tool():
        return {"error": "no account for jane@example.com"}

    tool()

    assert captured_logs[1]["error"] == "no account for [REDACTED_EMAIL]"


def test_instrument_redacts_before_truncating(captured_logs):
    """An email across the length limit must not survive in part."""
    text = "ERROR: " + "x" * 480 + " jane.doe@example.com"

    @instrument
    def tool():
        return text

    tool()

    logged = captured_logs[1]["error"]
    assert len(logged) == observability._MAX_ERROR_TEXT
    assert "jane" not in logged
    assert "@exa" not in logged
    # 488 characters precede the placeholder, so the cut keeps its first 12.
    assert logged.endswith(" [REDACTED_EM")


def test_instrument_redacts_the_error_text_on_the_span(fake_tracer):
    @instrument
    def tool():
        return {"error": "no account for jane@example.com"}

    tool()

    assert fake_tracer.spans["tool"].status.description == (
        "no account for [REDACTED_EMAIL]"
    )


class RaisingErrorProperty:
    @property
    def error(self):
        raise RuntimeError("lazy load failed")


class UnprintableError:
    def __str__(self):
        raise ValueError("cannot render")


def test_instrument_survives_an_error_property_that_raises(captured_logs, capsys):
    """Telemetry must not break a tool call that worked."""
    result = RaisingErrorProperty()

    @instrument
    def tool():
        return result

    assert tool() is result
    assert captured_logs[1]["outcome"] == "success"
    assert "lazy load failed" in capsys.readouterr().err


def test_instrument_survives_an_error_value_that_cannot_be_rendered(
    captured_logs, monkeypatch, capsys
):
    monkeypatch.setattr(observability, "_is_error_value", lambda value: True)
    result = ErrorResponse(error=UnprintableError())

    @instrument
    def tool():
        return result

    assert tool() is result
    assert captured_logs[1]["outcome"] == "success"
    assert "could not inspect the result of tool" in capsys.readouterr().err


async def test_instrument_logs_an_async_error_shaped_result_as_failed(captured_logs):
    @instrument
    async def tool():
        return {"status": "error", "error_message": "timed out"}

    assert await tool() == {"status": "error", "error_message": "timed out"}

    end = captured_logs[1]
    assert end["event"] == "tool.end"
    assert end["outcome"] == "error"
    assert end["error"] == "timed out"


def test_instrument_marks_the_span_failed_for_an_error_shaped_result(fake_tracer):
    @instrument
    def tool():
        return "ERROR: table not found"

    tool()

    span = fake_tracer.spans["tool"]
    assert span.attributes["outcome"] == "error"
    assert "duration_ms" in span.attributes
    assert span.exceptions == []
    assert span.status is not None
    assert span.status.description == "ERROR: table not found"


def test_span_error_status_failure_is_reported_not_raised(capsys):
    class BrokenSpan:
        def set_status(self, status):
            raise RuntimeError("exporter gone")

    observability._set_span_error_status(BrokenSpan(), "ERROR: x")

    assert "could not set error status on span" in capsys.readouterr().err
