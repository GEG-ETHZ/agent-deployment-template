"""Unit tests for deployment/scripts/read_traces.py — no network, no GCP credentials.

The script this replaces was a bash file that printed a Cloud *Logging* filter and
labelled it a Cloud Trace filter, then opened the console — it never queried anything,
so nothing about it could be tested or could fail visibly. Everything except the one
HTTP call is a pure function here, which is what these tests pin.
"""

from datetime import UTC, datetime, timedelta

import pytest

from deployment.scripts.read_traces import (
    build_params,
    console_url,
    format_trace,
    main,
    no_match_hint,
    parse_duration,
    tool_filter,
)

FIXED_NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("45s", timedelta(seconds=45)),
        ("30m", timedelta(minutes=30)),
        ("6h", timedelta(hours=6)),
        ("2d", timedelta(days=2)),
        (" 1h ", timedelta(hours=1)),
    ],
)
def test_parse_duration_accepts_gcloud_freshness_strings(value, expected):
    assert parse_duration(value) == expected


@pytest.mark.parametrize("value", ["", "1", "h", "1w", "-1h", "1.5h", "abc"])
def test_parse_duration_rejects_anything_else(value):
    with pytest.raises(ValueError, match="Invalid duration"):
        parse_duration(value)


def test_build_params_windows_backwards_from_now():
    params = build_params("2h", limit=10, trace_filter=None, now=FIXED_NOW)

    assert params["startTime"] == (FIXED_NOW - timedelta(hours=2)).isoformat()
    assert params["endTime"] == FIXED_NOW.isoformat()


def test_build_params_requests_root_spans_newest_first():
    """ROOTSPAN keeps the response to one span per trace; the list is a timeline."""
    params = build_params("1h", limit=10, trace_filter=None, now=FIXED_NOW)

    assert params["view"] == "ROOTSPAN"
    assert params["orderBy"] == "start desc"


def test_build_params_passes_limit_as_page_size():
    params = build_params("1h", limit=50, trace_filter=None, now=FIXED_NOW)

    assert params["pageSize"] == 50


def test_build_params_omits_filter_when_none_given():
    """Unfiltered by default: several agents share a project and Cloud Trace has no
    reliable per-agent label to narrow on."""
    params = build_params("1h", limit=10, trace_filter=None, now=FIXED_NOW)

    assert "filter" not in params


def test_build_params_includes_filter_when_given():
    params = build_params("1h", limit=10, trace_filter="span:web_search", now=FIXED_NOW)

    assert params["filter"] == "span:web_search"


def test_format_trace_renders_root_span_name_and_trace_id():
    line = format_trace(
        {
            "traceId": "abc123",
            "spans": [{"name": "web_search", "startTime": "2026-09-07T12:00:00.123Z"}],
        }
    )

    assert "web_search" in line
    assert "abc123" in line
    assert "2026-09-07T12:00:00" in line


def test_format_trace_handles_a_trace_with_no_spans():
    """The API can return a trace whose spans the view omitted — don't IndexError."""
    line = format_trace({"traceId": "abc123", "spans": []})

    assert "abc123" in line


def test_format_trace_handles_a_missing_spans_key():
    assert "abc123" in format_trace({"traceId": "abc123"})


def test_console_url_targets_the_requested_project():
    assert "project=my-project" in console_url("my-project")


def test_main_fails_without_a_project(monkeypatch, capsys):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

    assert main([]) == 1
    assert "GOOGLE_CLOUD_PROJECT" in capsys.readouterr().err


def test_main_fails_on_an_invalid_since_without_calling_the_api(monkeypatch, capsys):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-project")
    monkeypatch.setattr(
        "deployment.scripts.read_traces.fetch_traces",
        lambda *a, **kw: pytest.fail("the API must not be called on a bad argument"),
    )

    assert main(["--since", "1w"]) == 1
    assert "Invalid duration" in capsys.readouterr().err


def test_main_prints_each_returned_trace(monkeypatch, capsys):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-project")
    monkeypatch.setattr(
        "deployment.scripts.read_traces.fetch_traces",
        lambda project, params: [
            {"traceId": "t1", "spans": [{"name": "web_search", "startTime": "x"}]},
            {"traceId": "t2", "spans": [{"name": "get_current_datetime"}]},
        ],
    )

    assert main([]) == 0
    out = capsys.readouterr().out
    assert "web_search" in out
    assert "get_current_datetime" in out


def test_main_explains_an_empty_result(monkeypatch, capsys):
    """An empty list is the symptom of the bug this fixes, so it gets a diagnosis
    rather than silence."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-project")
    monkeypatch.setattr(
        "deployment.scripts.read_traces.fetch_traces", lambda project, params: []
    )

    assert main([]) == 0
    assert "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY" in capsys.readouterr().out


# --- --spans: tool spans are children of ADK's root span ---------------------
#
# Verified against a live deployment: a request produces `invoke_workflow root_agent`
# as the root, with the @instrument span nested several levels below it. The default
# ROOTSPAN view therefore never shows the spans this tooling exists to surface.


def test_build_params_requests_complete_view_for_spans():
    params = build_params("1h", limit=10, trace_filter=None, now=FIXED_NOW, spans=True)

    assert params["view"] == "COMPLETE"


def test_build_params_defaults_to_rootspan_view():
    """One line per trace by default -- COMPLETE pulls every child span of every trace."""
    params = build_params("1h", limit=10, trace_filter=None, now=FIXED_NOW)

    assert params["view"] == "ROOTSPAN"


def test_format_trace_lists_child_spans_when_requested():
    line = format_trace(
        {
            "traceId": "abc123",
            "spans": [
                {
                    "name": "invoke_workflow root_agent",
                    "startTime": "2026-09-07T20:44:14Z",
                },
                {"name": "execute_tool get_current_datetime"},
                {"name": "get_current_datetime"},
            ],
        },
        spans=True,
    )

    assert "invoke_workflow root_agent" in line
    assert "    get_current_datetime" in line
    assert len(line.splitlines()) == 3


def test_format_trace_shows_only_the_root_by_default():
    line = format_trace(
        {
            "traceId": "abc123",
            "spans": [
                {"name": "invoke_workflow root_agent", "startTime": "x"},
                {"name": "get_current_datetime"},
            ],
        }
    )

    assert len(line.splitlines()) == 1
    assert "get_current_datetime" not in line


def test_tool_filter_quotes_the_span_name_the_platform_writes():
    # Act
    result = tool_filter("web_search")

    # Assert: unquoted, Cloud Trace reads the tool name as a second term and
    # matches nothing
    assert result == 'span:"execute_tool web_search"'


def test_tool_filter_ignores_surrounding_whitespace():
    assert tool_filter(" web_search ") == 'span:"execute_tool web_search"'


@pytest.mark.parametrize(
    "name", ["", "  ", 'x" root:other', "web search", "span:web_search", "1st"]
)
def test_tool_filter_rejects_anything_but_a_function_name(name):
    with pytest.raises(ValueError, match="Invalid tool name"):
        tool_filter(name)


def test_main_sends_the_tool_filter_for_the_tool_option(monkeypatch, capsys):
    # Arrange
    sent = {}

    def fake_fetch(project, params):
        sent.update(params)
        return []

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-project")
    monkeypatch.setattr("deployment.scripts.read_traces.fetch_traces", fake_fetch)

    # Act
    exit_code = main(["--tool", "web_search"])

    # Assert
    assert exit_code == 0
    assert sent["filter"] == 'span:"execute_tool web_search"'
    assert 'filter: span:"execute_tool web_search"' in capsys.readouterr().out


def test_main_fails_on_an_invalid_tool_name_without_calling_the_api(
    monkeypatch, capsys
):
    # Arrange
    def must_not_be_called(project, params):
        raise AssertionError("the API was called")

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-project")
    monkeypatch.setattr(
        "deployment.scripts.read_traces.fetch_traces", must_not_be_called
    )

    # Act
    exit_code = main(["--tool", "web search"])

    # Assert
    assert exit_code == 1
    assert "Invalid tool name" in capsys.readouterr().err


def test_main_refuses_a_filter_together_with_a_tool(monkeypatch):
    # Arrange
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-project")

    # Act / Assert: two ways to narrow would leave it unclear which one applies
    with pytest.raises(SystemExit):
        main(["--tool", "web_search", "--filter", "root:invoke_workflow"])


def test_main_points_to_the_tool_option_when_a_bare_span_filter_matched_nothing(
    monkeypatch, capsys
):
    # Arrange
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-project")
    monkeypatch.setattr(
        "deployment.scripts.read_traces.fetch_traces", lambda project, params: []
    )

    # Act
    main(["--filter", "span:web_search"])

    # Assert
    assert "use --tool <tool_name>" in capsys.readouterr().out


def test_main_says_the_tool_was_not_called_when_the_tool_option_matched_nothing(
    monkeypatch, capsys
):
    # Arrange
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-project")
    monkeypatch.setattr(
        "deployment.scripts.read_traces.fetch_traces", lambda project, params: []
    )

    # Act
    main(["--tool", "web_search"])

    # Assert: the reader already used --tool, so they are not told to use it
    output = capsys.readouterr().out
    assert "No tool whose name starts with 'web_search' was called" in output
    assert "use --tool <tool_name>" not in output


@pytest.mark.parametrize(
    "trace_filter",
    [None, "root:invoke_workflow", 'span:"execute_tool web_search"'],
)
def test_no_match_hint_is_silent_when_the_filter_is_not_a_bare_span_filter(
    trace_filter,
):
    assert no_match_hint(None, trace_filter) is None


def test_main_refuses_an_empty_tool_name_without_calling_the_api(monkeypatch, capsys):
    # Arrange: as from --tool "$TOOL" with the variable unset
    def must_not_be_called(project, params):
        raise AssertionError("the API was called")

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-project")
    monkeypatch.setattr(
        "deployment.scripts.read_traces.fetch_traces", must_not_be_called
    )

    # Act
    exit_code = main(["--tool", ""])

    # Assert: not an unfiltered listing
    assert exit_code == 1
    assert "Invalid tool name" in capsys.readouterr().err


def test_main_gives_no_filter_hint_when_no_filter_was_set(monkeypatch, capsys):
    # Arrange
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-project")
    monkeypatch.setattr(
        "deployment.scripts.read_traces.fetch_traces", lambda project, params: []
    )

    # Act
    main([])

    # Assert
    assert "--tool <tool_name>" not in capsys.readouterr().out
