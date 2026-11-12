#!/usr/bin/env python3
"""Local evaluation runner: what `make eval` runs.

Usage:
    uv run python tests/evals/run_eval.py

The eval calls real models and is billed: each of the suite's cases runs the agent
(Gemini 2.5 Pro by default, one or more calls per case), and each `llm-rubric` assertion
makes one Gemini 2.5 Flash call to grade it. The grader always runs on Vertex AI with
Application Default Credentials (`gcloud auth application-default login`), in
GOOGLE_CLOUD_PROJECT. To check the suite's config and datasets without a key or a
login, run `make eval-check` instead.

The run is judged by tests/evals/enforce.py, the same check eval.yml applies in CI.
"""

import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

CONFIG = Path(__file__).parent / "promptfoo.yaml"
ENFORCE = Path(__file__).parent / "enforce.py"

# Keep in step with eval.yml (tests/unit/test_eval_suite.py checks it). An unpinned npx
# resolves at run time, so a promptfoo release could change local results, or what
# runs, without a commit here.
PROMPTFOO_VERSION = "0.123.1"

# The API key each non-Google provider reads (through LiteLLM).
PROVIDER_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def _is_true(value: str | None) -> bool:
    return (value or "").strip().lower() in ("true", "1")


def missing_settings(env: Mapping[str, str]) -> list[str]:
    """Return one line per setting the eval needs and `env` lacks; empty when complete."""
    missing = []
    if not env.get("GOOGLE_CLOUD_PROJECT"):
        missing.append(
            "GOOGLE_CLOUD_PROJECT is not set. The rubric grader calls Gemini on Vertex AI "
            "in this project, with Application Default Credentials "
            "(gcloud auth application-default login)."
        )
    provider = env.get("MODEL_PROVIDER", "google").lower()
    if provider == "google":
        if not _is_true(env.get("GOOGLE_GENAI_USE_VERTEXAI")) and not env.get(
            "GOOGLE_API_KEY"
        ):
            missing.append(
                "The agent has no Gemini credentials: set GOOGLE_GENAI_USE_VERTEXAI=TRUE "
                "(Vertex AI with Application Default Credentials, as in .env.example) "
                "or GOOGLE_API_KEY (AI Studio)."
            )
    elif provider in PROVIDER_KEYS:
        key = PROVIDER_KEYS[provider]
        if not env.get(key):
            missing.append(f"MODEL_PROVIDER={provider} needs {key}.")
    elif provider == "litellm" and not env.get("LITELLM_MODEL"):
        missing.append("MODEL_PROVIDER=litellm needs LITELLM_MODEL.")
    return missing


def main() -> None:
    # The Makefile exports .env, so this sees the same settings as `make dev`.
    env = os.environ.copy()
    missing = missing_settings(env)
    if missing:
        print("make eval cannot run yet:", file=sys.stderr)
        for line in missing:
            print(f"  - {line}", file=sys.stderr)
        print(
            "To check the suite without credentials, run `make eval-check`.",
            file=sys.stderr,
        )
        sys.exit(2)

    print("Running promptfoo evaluation (real model calls, billed to your project)...")
    print(f"Config: {CONFIG}\n")

    # Ensure promptfoo can access the current Python environment
    env["PYTHONPATH"] = str(Path(__file__).parent.parent.parent)

    # Disable OpenTelemetry to avoid context errors in the ADK
    env["OTEL_SDK_DISABLED"] = "true"
    env["PROMPTFOO_DISABLE_TELEMETRY"] = "1"

    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "output.json"
        # -j 2 matches eval.yml. promptfoo defaults to 4, which runs enough parallel
        # agent and grader calls to trip Vertex quota; the model then answers a
        # benign prompt with a "try again later" string and the suite fails for a
        # reason that has nothing to do with the agent.
        result = subprocess.run(
            [
                "npx",
                "--yes",
                f"promptfoo@{PROMPTFOO_VERSION}",
                "eval",
                "--config",
                str(CONFIG),
                "-j",
                "2",
                "-o",
                str(output),
            ],
            capture_output=False,
            env=env,
        )
        if not output.exists():
            sys.exit(result.returncode or 1)
        # promptfoo's exit code says nothing about errored or ungraded cases.
        verdict = subprocess.run([sys.executable, str(ENFORCE), str(output)])
    sys.exit(verdict.returncode)


if __name__ == "__main__":
    main()
