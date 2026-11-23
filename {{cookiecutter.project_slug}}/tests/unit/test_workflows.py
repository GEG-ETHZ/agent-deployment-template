"""The GitHub workflows run the versions they name.

Dependabot moves an action's commit SHA and its `# vX` comment, but never a `with:` input.
Where an input picks what actually runs, these tests catch the two drifting apart.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SECURITY_WORKFLOW = (REPO_ROOT / ".github" / "workflows" / "security.yml").read_text()

TRUFFLEHOG_COMMENT = re.compile(
    r"uses: trufflesecurity/trufflehog@[0-9a-f]{40} # v(\S+)"
)
TRUFFLEHOG_IMAGE = re.compile(r"^\s+version: \"([^\"]+)\"", re.MULTILINE)


def trufflehog_versions(workflow: str) -> tuple[str, str]:
    """Return the release named on the `uses:` line and the scanner image tag."""
    action = TRUFFLEHOG_COMMENT.search(workflow)
    image = TRUFFLEHOG_IMAGE.search(workflow)
    if action is None or image is None:
        raise ValueError(
            "security.yml has no SHA-pinned TruffleHog step with a version input"
        )
    return action.group(1), image.group(1)


def test_trufflehog_scanner_image_matches_the_pinned_action():
    # Arrange: the action is a wrapper around `docker run trufflehog:<version>`, so the
    # input, not the SHA, decides which scanner runs.
    action_version, image_version = trufflehog_versions(SECURITY_WORKFLOW)

    # Assert
    assert image_version == action_version, (
        f"TruffleHog action is v{action_version} but the scanner image is {image_version}; "
        f'set `version: "{action_version}"` in security.yml'
    )


def test_trufflehog_versions_reports_a_mismatch():
    # Arrange: the state a Dependabot bump leaves behind.
    workflow = (
        "      - uses: trufflesecurity/trufflehog@" + "a" * 40 + " # v3.100.0\n"
        "        with:\n"
        '          version: "3.97.5"\n'
    )

    # Act
    action_version, image_version = trufflehog_versions(workflow)

    # Assert
    assert (action_version, image_version) == ("3.100.0", "3.97.5")
