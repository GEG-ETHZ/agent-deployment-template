"""CI's grants name one GitHub repository, and that name is committed, not derived.

infra/agent/ci.tf grants the repository in Makefile's GITHUB_REPOSITORY. Reading it from the
`origin` remote of whoever applies meant a clone without a remote removed the grants, and a
fork as `origin` moved them to the fork.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = (REPO_ROOT / "Makefile").read_text()
ASSIGNMENT = re.compile(r"^GITHUB_REPOSITORY\s*(\??:?=)\s*(.*?)\s*$", re.MULTILINE)
OWNER_AND_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$")


def _assignment() -> tuple[str, str]:
    """Return the operator and the value of GITHUB_REPOSITORY in the Makefile."""
    match = ASSIGNMENT.search(MAKEFILE)
    assert match is not None, "Makefile defines no GITHUB_REPOSITORY"
    return match.group(1), match.group(2)


def test_github_repository_is_assigned_in_the_makefile():
    # Arrange / Act
    operator, _ = _assignment()

    # Assert
    assert operator


def test_github_repository_is_not_taken_from_the_environment_or_a_remote():
    # Arrange / Act
    operator, value = _assignment()

    # Assert: `:=` beats the environment (GitHub Actions sets GITHUB_REPOSITORY itself),
    # and a shell call to git would read whichever remote the applier happens to have.
    assert operator == ":="
    assert "$(shell" not in value and "git remote" not in value


def test_github_repository_is_owner_and_name_or_empty():
    # Arrange / Act
    _, value = _assignment()

    # Assert: empty switches CI's access off, which is a valid choice
    assert value == "" or OWNER_AND_NAME.match(value), value
