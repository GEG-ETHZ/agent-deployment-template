import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _project_name() -> str:
    """Read the project name from pyproject.toml so derived names stay in sync."""
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    with open(pyproject, "rb") as f:
        return tomllib.load(f)["project"]["name"]


def resolve_model():
    """Return the ADK-compatible model handle based on MODEL_PROVIDER env var.

    Supported values for MODEL_PROVIDER:
      google    (default) — Gemini 2.5 Pro via native ADK
      anthropic           — Claude via LiteLLM
      openai              — GPT-4o via LiteLLM
      litellm             — any model; set LITELLM_MODEL to the full model string
    """
    provider = os.getenv("MODEL_PROVIDER", "google").lower()

    if provider == "google":
        return "gemini-2.5-pro"

    from google.adk.models.lite_llm import LiteLlm  # noqa: PLC0415

    match provider:
        case "anthropic":
            return LiteLlm(model="anthropic/claude-opus-4-8")
        case "openai":
            return LiteLlm(model="openai/gpt-4o")
        case "litellm":
            model = os.environ["LITELLM_MODEL"]
            return LiteLlm(model=model)
        case _:
            raise ValueError(
                f"Unknown MODEL_PROVIDER: {provider!r}. "
                "Valid options: google, anthropic, openai, litellm"
            )


# The staging bucket `setup_gcp.sh` provisions is fully determined by the project id,
# so it does not have to be restated in .env -- keep this in step with BUCKET in
# deployment/scripts/setup_gcp.sh.
STAGING_BUCKET_SUFFIX = "-agent-staging"

# The deployed agent runs under its own resource-scoped Agent Identity. Beyond the
# project's Google-managed agent default access, infra/agent grants it its
# roles. See "Runtime identity" in AGENTS.md.
RUNTIME_IDENTITY_TYPE = "AGENT_IDENTITY"


def default_staging_bucket(project: str) -> str:
    """The staging bucket `setup_gcp.sh` provisions for this project."""
    return f"gs://{project}{STAGING_BUCKET_SUFFIX}"


def normalise_bucket(value: str) -> str:
    """Add the `gs://` scheme if the caller left it off.

    `setup_gcp.sh` prints the bucket as a bare name while the docs show it with the
    scheme, and Vertex wants a full `gs://` URI -- so accept either spelling rather
    than making the difference matter.
    """
    return value if value.startswith("gs://") else f"gs://{value}"


@dataclass
class DeploymentConfig:
    project: str
    location: str
    staging_bucket: str
    resource_name: str | None
    gcs_dir_name: str
    identity_type: str = RUNTIME_IDENTITY_TYPE

    @classmethod
    def from_env(cls) -> "DeploymentConfig":
        """Build the config from the environment.

        `GOOGLE_CLOUD_PROJECT` is the only required variable. The staging bucket is
        derived from it, matching what `setup_gcp.sh` provisions, and
        `GCS_STAGING_BUCKET` exists only to override that for a renamed bucket.

        Raises:
            KeyError: `GOOGLE_CLOUD_PROJECT` is not set.
        """
        project = os.environ["GOOGLE_CLOUD_PROJECT"]
        staging_bucket = os.getenv("GCS_STAGING_BUCKET")
        return cls(
            project=project,
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "europe-west1"),
            staging_bucket=(
                normalise_bucket(staging_bucket)
                if staging_bucket
                else default_staging_bucket(project)
            ),
            # Set by `make deploy-*` from the OpenTofu output; see infra/agent.
            resource_name=os.getenv("AGENT_ENGINE_RESOURCE_NAME") or None,
            # Staging subfolder, project-named so several agents can share one
            # bucket instead of colliding in the SDK's generic default.
            gcs_dir_name=_project_name(),
        )

    @property
    def runtime_env_vars(self) -> dict[str, str]:
        """Environment variables set on the deployed container.

        Deliberately minimal. Logs need nothing here: Agent Engine forwards stdout.
        Traces come from Agent Engine's built-in telemetry. Our own Cloud Trace
        exporter (CLOUD_TRACE_ENABLED) stays off when deployed: under Agent Identity
        the access token is bound to the agent's certificate, and the exporter, which
        does not use mTLS, is rejected with 401. Prompt and response text is not
        captured (OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT stays unset).
        See "Observability -> Destinations" in AGENTS.md.
        """
        return {"GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true"}
