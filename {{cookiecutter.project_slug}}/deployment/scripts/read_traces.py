#!/usr/bin/env python3
"""List this agent's Cloud Trace traces.

Tool spans are children of ADK's `invoke_workflow` root span, so the default
listing shows roots only -- pass `--spans` to expand them. See "Observability" in
AGENTS.md.

Usage:
    uv run python deployment/scripts/read_traces.py
    uv run python deployment/scripts/read_traces.py --spans
    uv run python deployment/scripts/read_traces.py --since 6h --limit 50
    uv run python deployment/scripts/read_traces.py --filter "span:web_search"

`gcloud` has no `trace` command group, so this calls the Cloud Trace v1 REST API
with Application Default Credentials. Unfiltered by default: Cloud Trace has no
per-agent label, so narrow with `--filter "span:<tool_name>"`.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from dotenv import load_dotenv

# Needed when run directly: only `make traces` exports .env, and this script does not
# import deployment/config.py, which is where load_dotenv() otherwise happens.
load_dotenv()

TRACE_API = "https://cloudtrace.googleapis.com/v1/projects/{project}/traces"
READONLY_SCOPE = "https://www.googleapis.com/auth/trace.readonly"

_DURATION_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
_DURATION_PATTERN = re.compile(r"^(\d+)([smhd])$")


def parse_duration(value: str) -> timedelta:
    """Parse a gcloud-style freshness string ("30m", "2h", "7d") into a timedelta."""
    match = _DURATION_PATTERN.match(value.strip())
    if match is None:
        raise ValueError(
            f"Invalid duration {value!r}. Use a number followed by s, m, h, or d "
            "(e.g. 30m, 6h, 2d)."
        )
    amount, unit = match.groups()
    return timedelta(**{_DURATION_UNITS[unit]: int(amount)})


def build_params(
    since: str,
    limit: int,
    trace_filter: str | None,
    now: datetime | None = None,
    spans: bool = False,
) -> dict[str, Any]:
    """Build the query string for projects.traces.list.

    `now` is injectable so tests can assert on a fixed window instead of the clock.
    """
    current = now or datetime.now(tz=UTC)
    params: dict[str, Any] = {
        "startTime": (current - parse_duration(since)).isoformat(),
        "endTime": current.isoformat(),
        "pageSize": limit,
        # ROOTSPAN returns each trace's root span only -- enough to list what ran,
        # without pulling every child span of every trace. COMPLETE is what surfaces
        # the @instrument tool spans, which are children of ADK's invoke_workflow.
        "view": "COMPLETE" if spans else "ROOTSPAN",
        "orderBy": "start desc",
    }
    if trace_filter:
        params["filter"] = trace_filter
    return params


def format_trace(trace: dict[str, Any], spans: bool = False) -> str:
    """Render one trace from the API response.

    One line by default; with `spans`, an extra indented line per span so the
    `@instrument` tool spans nested under ADK's root span are visible.
    """
    trace_id = trace.get("traceId", "?")
    trace_spans = trace.get("spans") or []
    if not trace_spans:
        return f"{trace_id}  (no spans returned)"
    root = trace_spans[0]
    start = root.get("startTime", "")[:19]
    header = f"[{start}] {root.get('name', '?')}  trace={trace_id}"
    if not spans:
        return header
    lines = [header]
    lines.extend(f"    {sp.get('name', '?')}" for sp in trace_spans[1:])
    return "\n".join(lines)


def console_url(project: str) -> str:
    """Cloud Trace console link for the project, printed alongside the results."""
    return f"https://console.cloud.google.com/traces/list?project={project}"


def fetch_traces(project: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Call the Cloud Trace v1 API and return the traces it reports."""
    import google.auth  # noqa: PLC0415
    from google.auth.transport.requests import AuthorizedSession  # noqa: PLC0415

    credentials, _ = google.auth.default(scopes=[READONLY_SCOPE])
    session = AuthorizedSession(credentials)
    response = session.get(TRACE_API.format(project=project), params=params)
    response.raise_for_status()
    return response.json().get("traces") or []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List this agent's Cloud Trace traces")
    parser.add_argument("--since", default="1h", help="Lookback window (default: 1h)")
    parser.add_argument(
        "--limit", type=int, default=20, help="Max traces to return (default: 20)"
    )
    parser.add_argument(
        "--filter",
        dest="trace_filter",
        default=None,
        help='Cloud Trace filter, e.g. "span:web_search"',
    )
    parser.add_argument(
        "--spans",
        action="store_true",
        help="List every span in each trace, not just the root span",
    )
    args = parser.parse_args(argv)

    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project:
        print("Set GOOGLE_CLOUD_PROJECT in .env or export it first.", file=sys.stderr)
        return 1

    try:
        params = build_params(
            args.since, args.limit, args.trace_filter, spans=args.spans
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Cloud Trace for {project} (last {args.since}, limit {args.limit})")
    if args.trace_filter:
        print(f"  filter: {args.trace_filter}")
    print("")

    traces = fetch_traces(project, params)
    for trace in traces:
        print(format_trace(trace, spans=args.spans))

    if not traces:
        print("No traces matched.")
        print("")
        print("If the agent has served traffic in this window, check that the deployed")
        print(
            "resource has GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true -- redeploy"
        )
        print(
            "with the current deploy.py, which sets it, then invoke a tool and retry."
        )

    print("")
    print(f"Console: {console_url(project)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
