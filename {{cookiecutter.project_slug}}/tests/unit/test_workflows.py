"""The GitHub workflows run the versions they name.

Dependabot moves an action's commit SHA and its `# vX` comment, but never a `with:` input.
Where an input picks what actually runs, these tests catch the two drifting apart.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SECURITY_WORKFLOW = (REPO_ROOT / ".github" / "workflows" / "security.yml").read_text()

TRUFFLEHOG_ACTION = "trufflesecurity/trufflehog@"
# YAML drops comments, so the release on the `uses:` line is read from the raw text.
TRUFFLEHOG_RELEASE_COMMENT = re.compile(
    r"uses: trufflesecurity/trufflehog@[0-9a-f]{40} # v(\S+)"
)


def trufflehog_versions(workflow: str) -> tuple[str, str]:
    """Return the release named on TruffleHog's `uses:` line and its `version:` input."""
    steps = [
        step
        for job in yaml.safe_load(workflow)["jobs"].values()
        for step in job.get("steps", [])
        if str(step.get("uses", "")).startswith(TRUFFLEHOG_ACTION)
    ]
    release = TRUFFLEHOG_RELEASE_COMMENT.search(workflow)
    if len(steps) != 1 or release is None or "version" not in steps[0].get("with", {}):
        raise ValueError(
            "the workflow needs one SHA-pinned TruffleHog step with a `# vX` comment "
            "and a version input"
        )
    return release.group(1), str(steps[0]["with"]["version"])


def workflow_with(trufflehog_line: str, version_input: str) -> str:
    """Build a workflow whose first step has a `version:` input of its own."""
    return (
        "jobs:\n"
        "  audit:\n"
        "    steps:\n"
        "      - uses: astral-sh/setup-uv@" + "b" * 40 + " # v10.3.3\n"
        "        with:\n"
        '          version: "0.9.5"\n'
        "  scan:\n"
        "    steps:\n"
        f"      - uses: {trufflehog_line}\n"
        "        with:\n"
        f"          version: {version_input}\n"
    )


def test_trufflehog_scanner_image_matches_the_pinned_action():
    # Arrange: the action is a wrapper around `docker run trufflehog:<version>`, so the
    # input, not the SHA, decides which scanner runs.
    workflow = SECURITY_WORKFLOW

    # Act
    release, version_input = trufflehog_versions(workflow)

    # Assert
    assert version_input == release, (
        f"TruffleHog action is v{release} but the scanner image is {version_input}; "
        f'set `version: "{release}"` in security.yml'
    )


@pytest.mark.parametrize("version_input", ['"3.97.5"', "'3.97.5'", "3.97.5"])
def test_trufflehog_versions_reads_the_trufflehog_step_only(version_input):
    # Arrange: the state a Dependabot bump leaves behind, after another step's `version:`.
    workflow = workflow_with(
        "trufflesecurity/trufflehog@" + "a" * 40 + " # v3.100.0", version_input
    )

    # Act
    release, read_input = trufflehog_versions(workflow)

    # Assert
    assert (release, read_input) == ("3.100.0", "3.97.5")


def test_trufflehog_versions_refuses_a_step_pinned_by_tag():
    # Arrange
    workflow = workflow_with("trufflesecurity/trufflehog@v3.97.5", '"3.97.5"')

    # Act / Assert
    with pytest.raises(ValueError, match="one SHA-pinned TruffleHog step"):
        trufflehog_versions(workflow)
