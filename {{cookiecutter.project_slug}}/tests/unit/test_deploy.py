"""Unit tests for the Agent Engine deploy path — no network, no GCP credentials required.

`deploy()` imports `vertexai`, `vertexai.agent_engines` and `agent.agent.root_agent`
inside the function body, so patching each at its source module keeps every test here
offline: nothing is pickled, uploaded, or billed. `run_smoke_test` and `create` are
patched too, only to prove deploy() calls neither.

This is the highest-blast-radius code in the template — it ships the agent to production —
so the tests below pin the behaviour that is easy to break silently: that it only ever
updates the engine OpenTofu created, what gets handed to that update, and that the agent
stays on its own Agent Identity rather than a shared service account.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from deployment.deploy import deploy

RESOURCE = "projects/p/locations/l/reasoningEngines/42"


@pytest.fixture
def deploy_env(monkeypatch, tmp_path):
    """Deploy-time environment, with a CWD that absorbs `.agent_engine_resource`.

    The engine already exists: OpenTofu (infra/agent) creates it, and `make deploy-*`
    passes its name in AGENT_ENGINE_RESOURCE_NAME.
    """
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project-123")
    monkeypatch.setenv("GCS_STAGING_BUCKET", "gs://test-staging-bucket")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "europe-west1")
    monkeypatch.setenv("AGENT_ENGINE_RESOURCE_NAME", RESOURCE)
    # deploy() writes .agent_engine_resource relative to the CWD, not the project root.
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def deps():
    """Patched Vertex AI surface. `update` yields the deployed remote agent."""
    remote_agent = Mock()
    remote_agent.resource_name = RESOURCE

    with (
        patch("vertexai.init") as init,
        patch("vertexai.agent_engines.get") as get,
        patch("vertexai.agent_engines.create") as create,
        patch(
            "deployment.scripts.health_check.run_smoke_test", return_value=True
        ) as smoke,
    ):
        get.return_value.update.return_value = remote_agent
        yield SimpleNamespace(
            init=init, get=get, create=create, smoke=smoke, remote_agent=remote_agent
        )


def update_kwargs(deps) -> dict:
    """The keyword arguments the deploy passed to the existing engine's update()."""
    return deps.get.return_value.update.call_args.kwargs


def test_deploy_updates_the_engine_opentofu_created(deploy_env, deps):
    deploy("dev")

    deps.get.assert_called_once_with(RESOURCE)
    deps.get.return_value.update.assert_called_once()


def test_deploy_never_creates_an_engine(deploy_env, deps):
    """A created engine would be a second agent with its own identity, outside the
    OpenTofu state, and without the grants infra/agent makes."""
    deploy("dev")

    deps.create.assert_not_called()


def test_deploy_refuses_to_run_without_a_resource_name(deploy_env, deps, monkeypatch):
    """Fail before pickling or uploading anything, and say where the name comes from."""
    monkeypatch.delenv("AGENT_ENGINE_RESOURCE_NAME")

    with (
        patch("deployment.deploy.locked_requirements") as requirements,
        pytest.raises(ValueError, match="AGENT_ENGINE_RESOURCE_NAME"),
    ):
        deploy("dev")

    requirements.assert_not_called()
    deps.init.assert_not_called()
    deps.create.assert_not_called()


def test_deploy_initialises_vertexai_with_staging_bucket(deploy_env, deps):
    deploy("dev")

    deps.init.assert_called_once_with(
        project="test-project-123",
        location="europe-west1",
        staging_bucket="gs://test-staging-bucket",
    )


def test_deploy_ships_agent_and_prompts_as_extra_packages(deploy_env, deps):
    """The pickled agent references agent.tools.* by module path, so both must travel."""
    deploy("dev")

    assert update_kwargs(deps)["extra_packages"] == ["agent", "prompts"]


def test_deploy_does_not_send_display_name(deploy_env, deps):
    """The display name belongs to the engine OpenTofu manages, not to a code deploy."""
    deploy("dev")

    assert "display_name" not in update_kwargs(deps)


def test_deploy_writes_resource_name_file(deploy_env, deps):
    """deploy.yml reads this file to learn the resource name after the deploy."""
    deploy("dev")

    assert (deploy_env / ".agent_engine_resource").read_text() == RESOURCE + "\n"


def test_deploy_leaves_the_smoke_test_to_the_health_check_step(deploy_env, deps):
    """`make deploy-*` runs health_check.py, with retries, after the code is live."""
    deploy("dev")

    deps.smoke.assert_not_called()


def test_deploy_env_argument_is_informational_only(deploy_env, deps):
    """`--env dev` does not retarget anything: project/location/bucket come from the
    environment, and the engine from AGENT_ENGINE_RESOURCE_NAME."""
    deploy("dev")
    dev_kwargs = deps.init.call_args.kwargs

    deps.init.reset_mock()
    deploy("prod")

    assert deps.init.call_args.kwargs == dev_kwargs


def test_deploy_keeps_the_engine_on_agent_identity(deploy_env, deps):
    """Matches the identity_type OpenTofu sets; a service account would move the
    agent off its own principal and the grants made to it."""
    deploy("dev")

    assert update_kwargs(deps)["identity_type"] == "AGENT_IDENTITY"
    assert "service_account" not in update_kwargs(deps)


def test_deploy_sends_the_local_python_version_with_the_code(deploy_env, deps):
    """update() builds its request through the SDK's builder; during the deploy that
    request must carry the Python the agent is pickled with, or an engine OpenTofu
    created builds on the API default, 3.10."""
    from google.cloud.aiplatform_v1.types import ReasoningEngine, ReasoningEngineSpec
    from google.cloud.aiplatform_v1.types.reasoning_engine_service import (
        UpdateReasoningEngineRequest,
    )
    from google.protobuf import field_mask_pb2
    from vertexai.agent_engines import _agent_engines as sdk

    from deployment.python_version import local_python_version

    shipped = UpdateReasoningEngineRequest(
        reasoning_engine=ReasoningEngine(
            spec=ReasoningEngineSpec(
                package_spec=ReasoningEngineSpec.PackageSpec(
                    pickle_object_gcs_uri="gs://b/a/agent_engine.pkl"
                )
            )
        ),
        update_mask=field_mask_pb2.FieldMask(
            paths=["spec.package_spec.pickle_object_gcs_uri"]
        ),
    )
    sent = []

    def sdk_update(**_):
        sent.append(
            sdk._generate_update_request_or_raise(
                resource_name=RESOURCE, staging_bucket="gs://b"
            )
        )
        return deps.remote_agent

    deps.get.return_value.update.side_effect = sdk_update
    with patch.object(sdk, "_generate_update_request_or_raise", return_value=shipped):
        deploy("dev")

    package_spec = sent[0].reasoning_engine.spec.package_spec
    assert package_spec.python_version == local_python_version()
    assert "spec.package_spec.python_version" in sent[0].update_mask.paths


def test_deploy_enables_observability_on_the_deployed_resource(deploy_env, deps):
    """Agent Engine's telemetry is what traces the deployed agent; the SDK alone would
    send "unspecified", which an engine OpenTofu created resolves to disabled."""
    deploy("dev")

    assert update_kwargs(deps)["env_vars"] == {
        "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
        "OTEL_SEMCONV_STABILITY_OPT_IN": "gen_ai_latest_experimental",
    }


def _locked_version(package: str) -> str:
    """The version uv.lock resolves `package` to."""
    import tomllib
    from pathlib import Path

    lockfile = Path(__file__).parent.parent.parent / "uv.lock"
    with open(lockfile, "rb") as handle:
        packages = tomllib.load(handle)["package"]
    return next(entry["version"] for entry in packages if entry["name"] == package)


@pytest.mark.parametrize("package", ["google-adk", "cloudpickle", "pydantic"])
def test_deploy_pins_requirements_to_the_lockfile(deploy_env, deps, package):
    """The container must install exactly what the agent was pickled against. Version
    floors let it resolve newer releases: google-adk>=1.0.0 once unpickled a 2.2.0 agent
    under 2.9.2, and every request failed. cloudpickle is transitive, and a mismatch
    there breaks unpickling at container start."""
    deploy("dev")

    assert (
        f"{package}=={_locked_version(package)}" in update_kwargs(deps)["requirements"]
    )


def test_deploy_requirements_carry_no_comments_or_dev_tools(deploy_env, deps):
    """The SDK parses each line as a requirement; dev tools do not belong in production."""
    deploy("dev")

    requirements = update_kwargs(deps)["requirements"]
    assert all(line and not line.startswith(("#", "-")) for line in requirements)
    assert not any(line.startswith(("pytest==", "ruff==")) for line in requirements)


def test_deploy_fails_before_uploading_when_the_lockfile_cannot_be_exported(
    deploy_env, deps
):
    """Deploying without pins would silently bring back the version drift."""
    import subprocess

    failure = subprocess.CalledProcessError(2, ["uv"], stderr="uv.lock not found")
    with (
        patch("deployment.deploy.subprocess.run", side_effect=failure),
        pytest.raises(RuntimeError, match="uv.lock not found"),
    ):
        deploy("dev")

    deps.get.return_value.update.assert_not_called()
