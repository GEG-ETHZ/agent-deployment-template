"""The promptfoo eval suite is well-formed, checked without a key or a model call.

`make eval` calls real models and needs credentials. These tests run in `make test` and
in CI on every pull request, and alone as `make eval-check`: they catch a broken config,
a missing or malformed dataset, and settings that would make the grader fail to log in,
before anyone spends a model call on it.
"""

import json
import re
from pathlib import Path

import pytest
import yaml

from deployment.config import PROVIDERS
from tests.evals import run_eval

REPO_ROOT = Path(__file__).resolve().parents[2]
EVALS = REPO_ROOT / "tests" / "evals"
CONFIG = yaml.safe_load((EVALS / "promptfoo.yaml").read_text())
EVAL_WORKFLOW = (REPO_ROOT / ".github" / "workflows" / "eval.yml").read_text()

# The assertion types the datasets use today. A new type is fine; add it here once it
# has been seen to work, so a typo such as `not-contain` is not silently ignored.
KNOWN_ASSERTIONS = {"contains", "contains-any", "not-contains", "llm-rubric"}


def _dataset_paths() -> list[Path]:
    paths = []
    for entry in CONFIG["tests"]:
        assert entry.startswith("file://"), entry
        paths.append(EVALS / entry.removeprefix("file://"))
    return paths


def _cases() -> list[tuple[str, int, dict]]:
    cases = []
    for path in _dataset_paths():
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if line.strip():
                cases.append((path.name, number, json.loads(line)))
    return cases


def test_every_dataset_exists():
    # Act
    missing = [str(path) for path in _dataset_paths() if not path.is_file()]

    # Assert
    assert missing == []


def test_provider_file_exists():
    # Arrange
    provider = CONFIG["providers"][0]["id"]

    # Act / Assert
    assert provider.startswith("python:")
    assert (EVALS / provider.removeprefix("python:")).is_file()


@pytest.mark.parametrize(("dataset", "line", "case"), _cases())
def test_case_is_well_formed(dataset: str, line: int, case: dict):
    # Assert
    where = f"{dataset}:{line}"
    assert case.get("description"), f"{where} has no description"
    assert isinstance(case.get("vars", {}).get("prompt"), str), f"{where} has no prompt"
    assert case["vars"]["prompt"].strip(), f"{where} has an empty prompt"
    assertions = case.get("assert")
    assert isinstance(assertions, list) and assertions, f"{where} asserts nothing"
    for assertion in assertions:
        assert assertion.get("type") in KNOWN_ASSERTIONS, f"{where}: {assertion}"
        assert assertion.get("value"), f"{where}: {assertion} has no value"


def test_case_descriptions_are_unique():
    # Arrange
    descriptions = [case["description"] for _, _, case in _cases()]

    # Act
    duplicates = {d for d in descriptions if descriptions.count(d) > 1}

    # Assert: the description is how a failure is reported
    assert duplicates == set()


def test_threshold_is_a_fraction():
    # Assert
    assert 0 < CONFIG["threshold"] <= 1


def test_grader_runs_on_vertex_with_application_default_credentials():
    # Arrange
    grader = CONFIG["defaultTest"]["options"]["provider"]

    # Assert: with express mode on, promptfoo sends GOOGLE_API_KEY to Vertex whenever it
    # is set, and Vertex refuses it -- every rubric assertion then fails ungraded.
    assert grader["id"].startswith("vertex:")
    assert grader["config"]["expressMode"] is False


def test_local_and_ci_runs_use_the_same_promptfoo():
    # Arrange
    pinned = re.findall(r"promptfoo@([0-9][^\s]*)", EVAL_WORKFLOW)

    # Assert
    assert pinned == [run_eval.PROMPTFOO_VERSION]


def test_ci_leaves_the_verdict_to_enforce():
    # Assert: promptfoo exits 100 when any case fails, which would fail the run step and
    # skip the Enforce step, so neither the threshold nor the grader-error report ran.
    assert 'PROMPTFOO_FAILED_TEST_EXIT_CODE: "0"' in EVAL_WORKFLOW
    assert "tests/evals/enforce.py output.json" in EVAL_WORKFLOW


def test_ci_eval_sends_no_api_key():
    # Assert: an API key in the environment would switch promptfoo's grader to express
    # mode on a promptfoo that ignores the config, and the agent to AI Studio.
    assert "GOOGLE_API_KEY" not in EVAL_WORKFLOW


def test_complete_vertex_settings_are_accepted():
    # Arrange
    env = {"GOOGLE_CLOUD_PROJECT": "p", "GOOGLE_GENAI_USE_VERTEXAI": "TRUE"}

    # Act / Assert
    assert run_eval.missing_settings(env) == []


def test_api_key_alone_is_enough_for_the_agent_but_not_the_grader():
    # Arrange
    env = {"GOOGLE_API_KEY": "k"}  # pragma: allowlist secret

    # Act
    missing = run_eval.missing_settings(env)

    # Assert: the grader still needs a project on Vertex
    assert len(missing) == 1
    assert "GOOGLE_CLOUD_PROJECT" in missing[0]


def test_google_agent_without_credentials_is_reported():
    # Arrange
    env = {"GOOGLE_CLOUD_PROJECT": "p", "GOOGLE_GENAI_USE_VERTEXAI": "FALSE"}

    # Act
    missing = run_eval.missing_settings(env)

    # Assert
    assert len(missing) == 1
    assert "GOOGLE_GENAI_USE_VERTEXAI=TRUE" in missing[0]


@pytest.mark.parametrize("provider", ["gemini", ""])
def test_unknown_or_empty_provider_is_reported(provider: str):
    # Arrange: resolve_model() raises on both, so every case would error
    env = {"GOOGLE_CLOUD_PROJECT": "p", "MODEL_PROVIDER": provider}

    # Act
    missing = run_eval.missing_settings(env)

    # Assert
    assert len(missing) == 1
    assert "is not one of" in missing[0]


def test_every_provider_has_a_settings_rule():
    # Assert: a provider added to deployment/config.py must get its check here too
    assert set(PROVIDERS) == {"google"} | set(run_eval.PROVIDER_SETTINGS)


@pytest.mark.parametrize(
    ("provider", "setting"),
    [
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
        ("litellm", "LITELLM_MODEL"),
    ],
)
def test_other_providers_need_their_own_setting(provider: str, setting: str):
    # Arrange
    env = {"GOOGLE_CLOUD_PROJECT": "p", "MODEL_PROVIDER": provider}

    # Act
    missing = run_eval.missing_settings(env)

    # Assert
    assert len(missing) == 1
    assert setting in missing[0]
