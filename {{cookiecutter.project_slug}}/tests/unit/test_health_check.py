"""Unit tests for the standalone health check — no network, no GCP credentials required.

`check_resource` imports `vertexai` and `vertexai.agent_engines` inside the function body,
so patching them at their source module is enough to keep every test below offline — no
`vertexai.init` call reaches Google, and no resource is ever fetched.
"""

from unittest.mock import Mock, patch

import pytest

from deployment.scripts.health_check import check_resource, run_smoke_test

SESSION_ID = "session-1"


def make_remote_agent(events: list[dict]) -> Mock:
    """A deployed agent whose session creation succeeds and whose query yields `events`."""
    remote_agent = Mock()
    remote_agent.create_session.return_value = {"id": SESSION_ID}
    remote_agent.stream_query.return_value = iter(events)
    return remote_agent


def test_run_smoke_test_passes_when_events_returned():
    remote_agent = make_remote_agent([{"type": "final_response"}])

    assert run_smoke_test(remote_agent) is True


def test_run_smoke_test_fails_when_no_events_returned():
    remote_agent = make_remote_agent([])

    assert run_smoke_test(remote_agent) is False


def test_run_smoke_test_passes_message_and_user_id_through():
    remote_agent = make_remote_agent([{"type": "final_response"}])

    run_smoke_test(remote_agent, message="hello", user_id="tester")

    remote_agent.stream_query.assert_called_once_with(
        message="hello", user_id="tester", session_id=SESSION_ID
    )


def test_run_smoke_test_queries_a_session_created_in_a_separate_call():
    """The console playground and real clients create a session, then query it, as two
    requests that can land on different replicas. A query without a session creates
    one inside the same request, so it passes even when that path is broken."""
    remote_agent = make_remote_agent([{"type": "final_response"}])

    run_smoke_test(remote_agent, user_id="tester")

    remote_agent.create_session.assert_called_once_with(user_id="tester")
    assert remote_agent.stream_query.call_args.kwargs["session_id"] == SESSION_ID


@pytest.fixture(autouse=True)
def no_sleep():
    """check_resource waits between attempts; tests must not."""
    with patch("deployment.scripts.health_check.time.sleep") as sleep:
        yield sleep


@pytest.fixture
def deployed_resource_env(monkeypatch):
    """Env for a project that already has a deployed Agent Engine resource."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project-123")
    monkeypatch.setenv("GCS_STAGING_BUCKET", "gs://test-staging-bucket")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "europe-west1")
    monkeypatch.setenv(
        "AGENT_ENGINE_RESOURCE_NAME", "projects/p/locations/l/reasoningEngines/1"
    )


def test_check_resource_returns_false_when_resource_name_unset(monkeypatch):
    """Without a deployed resource there is nothing to check — fail, don't deploy one."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project-123")
    monkeypatch.setenv("GCS_STAGING_BUCKET", "gs://test-staging-bucket")
    monkeypatch.delenv("AGENT_ENGINE_RESOURCE_NAME", raising=False)

    with patch("vertexai.init") as mock_init:
        assert check_resource("ping", "health-check") is False

    mock_init.assert_not_called()


def test_check_resource_passes_when_events_returned(deployed_resource_env):
    remote_agent = make_remote_agent([{"type": "final_response"}])

    with patch("vertexai.init"), patch("vertexai.agent_engines.get") as mock_get:
        mock_get.return_value = remote_agent

        assert check_resource("ping", "health-check") is True

    mock_get.assert_called_once_with("projects/p/locations/l/reasoningEngines/1")


def test_check_resource_fails_when_no_events_returned(deployed_resource_env):
    remote_agent = make_remote_agent([])

    with patch("vertexai.init"), patch("vertexai.agent_engines.get") as mock_get:
        mock_get.return_value = remote_agent

        assert check_resource("ping", "health-check") is False


def test_check_resource_initialises_vertexai_with_project_and_location(
    deployed_resource_env,
):
    """No staging bucket here — a health check reads an existing resource, it deploys nothing."""
    remote_agent = make_remote_agent([{"type": "final_response"}])

    with (
        patch("vertexai.init") as mock_init,
        patch("vertexai.agent_engines.get", return_value=remote_agent),
    ):
        check_resource("ping", "health-check")

    mock_init.assert_called_once_with(
        project="test-project-123", location="europe-west1"
    )


def test_check_resource_forwards_message_and_user_id(deployed_resource_env):
    remote_agent = make_remote_agent([{"type": "final_response"}])

    with (
        patch("vertexai.init"),
        patch("vertexai.agent_engines.get", return_value=remote_agent),
    ):
        check_resource("custom message", "custom-user")

    remote_agent.stream_query.assert_called_once_with(
        message="custom message", user_id="custom-user", session_id=SESSION_ID
    )


def test_check_resource_retries_until_the_agent_answers(
    deployed_resource_env, no_sleep
):
    """A fresh agent identity's grants take a minute or two to propagate, so the
    first queries can fail with PermissionDenied before the agent works."""
    remote_agent = make_remote_agent([{"type": "final_response"}])
    remote_agent.stream_query.side_effect = [
        PermissionError("aiplatform.endpoints.predict denied"),
        iter([{"type": "final_response"}]),
    ]

    with (
        patch("vertexai.init"),
        patch("vertexai.agent_engines.get", return_value=remote_agent),
    ):
        assert (
            check_resource("ping", "health-check", attempts=3, retry_delay_s=5) is True
        )

    assert remote_agent.stream_query.call_count == 2
    no_sleep.assert_called_once_with(5)


def test_check_resource_gives_up_after_the_last_attempt(
    deployed_resource_env, no_sleep
):
    remote_agent = make_remote_agent([])

    with (
        patch("vertexai.init"),
        patch("vertexai.agent_engines.get", return_value=remote_agent),
    ):
        assert (
            check_resource("ping", "health-check", attempts=3, retry_delay_s=5) is False
        )

    assert remote_agent.stream_query.call_count == 3
    # No wait after the final attempt: nothing follows it.
    assert no_sleep.call_count == 2


def test_check_resource_rejects_fewer_than_one_attempt(deployed_resource_env):
    with pytest.raises(ValueError, match="attempts"):
        check_resource("ping", "health-check", attempts=0)
