#!/usr/bin/env python3
"""Post-deployment health check for a Vertex AI Agent Engine resource.

Runs the smoke test (send a message, require at least one event back) against
an already-deployed resource: after `make deploy-*` has granted the agent
identity its roles, or on its own, e.g. right after a rollback.

A new agent identity's role grants take a minute or two to propagate, so the
check retries before it gives up.

Usage:
    uv run python deployment/scripts/health_check.py
    uv run python deployment/scripts/health_check.py --message "hello" --user-id healthcheck
"""

import argparse
import logging
import os
import sys
import time

# Ensure the project root is on the path when run as a script.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Enough to outlast IAM propagation for a freshly granted agent identity (~2 minutes).
DEFAULT_ATTEMPTS = 6
DEFAULT_RETRY_DELAY_S = 20.0


def run_smoke_test(
    remote_agent, message: str = "ping", user_id: str = "smoke-test"
) -> bool:
    """Send `message` to `remote_agent` and require at least one event back.

    `remote_agent` is whatever `agent_engines.create/update/get` returns — a
    deployed ADK agent exposes `stream_query` (a generator of event dicts),
    not `query`.

    The session is created in its own request first, as the console playground
    and real clients do. Querying without one creates it inside the same request,
    which passes even when sessions do not survive between requests.
    """
    session = remote_agent.create_session(user_id=user_id)  # type: ignore[attr-defined]
    events = list(
        remote_agent.stream_query(  # type: ignore[attr-defined]
            message=message, user_id=user_id, session_id=session["id"]
        )
    )
    if not events:
        logger.error("Health check failed: no events returned.")
        return False

    logger.info("Health check passed: %d event(s) returned.", len(events))
    return True


def smoke_test_with_retries(
    remote_agent, message: str, user_id: str, attempts: int, retry_delay_s: float
) -> bool:
    """Run the smoke test up to `attempts` times, waiting `retry_delay_s` in between.

    A failed query is logged and retried rather than raised: until IAM propagates,
    a correctly deployed agent answers with PermissionDenied.
    """
    for attempt in range(1, attempts + 1):
        try:
            if run_smoke_test(remote_agent, message=message, user_id=user_id):
                return True
        except Exception as exc:  # noqa: BLE001 - logged and retried, then reported
            logger.warning("Attempt %d/%d raised: %s", attempt, attempts, exc)
        if attempt < attempts:
            logger.info(
                "Retrying in %.0fs (attempt %d/%d)...", retry_delay_s, attempt, attempts
            )
            time.sleep(retry_delay_s)

    logger.error("Health check failed after %d attempt(s).", attempts)
    return False


def check_resource(
    message: str,
    user_id: str,
    attempts: int = DEFAULT_ATTEMPTS,
    retry_delay_s: float = DEFAULT_RETRY_DELAY_S,
) -> bool:
    """Fetch the resource named by AGENT_ENGINE_RESOURCE_NAME and smoke-test it.

    Raises:
        ValueError: `attempts` is below 1.
    """
    if attempts < 1:
        raise ValueError(f"attempts must be at least 1, got {attempts}")

    import vertexai
    from vertexai import agent_engines

    from deployment.config import DeploymentConfig

    config = DeploymentConfig.from_env()

    if not config.resource_name:
        logger.error(
            "AGENT_ENGINE_RESOURCE_NAME is not set — health check needs an existing "
            "deployed resource to query, not a fresh deploy."
        )
        return False

    logger.info("Health-checking: %s", config.resource_name)

    vertexai.init(project=config.project, location=config.location)
    remote_agent = agent_engines.get(config.resource_name)

    return smoke_test_with_retries(
        remote_agent, message, user_id, attempts=attempts, retry_delay_s=retry_delay_s
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run a standalone health check against a deployed Agent Engine resource"
    )
    parser.add_argument(
        "--message",
        default="ping",
        help="Message to send for the smoke test (default: ping)",
    )
    parser.add_argument(
        "--user-id",
        default="health-check",
        help="User ID to attribute the smoke-test query to (default: health-check)",
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=DEFAULT_ATTEMPTS,
        help=f"Queries to try before failing (default: {DEFAULT_ATTEMPTS})",
    )
    args = parser.parse_args()
    sys.exit(
        0 if check_resource(args.message, args.user_id, attempts=args.attempts) else 1
    )
