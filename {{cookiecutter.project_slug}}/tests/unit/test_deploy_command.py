"""/deploy hands the OpenTofu apply to a person and only ships the code itself.

An apply changes the production project's IAM grants, and its confirmation prompt is the
only review. A coding agent that ran it would meet that prompt and could reach for
-auto-approve, so the command tells it not to apply at all.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_COMMAND = (REPO_ROOT / ".claude" / "commands" / "deploy.md").read_text()


def test_deploy_command_does_not_tell_the_agent_to_run_the_combined_deploy():
    # Arrange / Act / Assert: `make deploy-prod` applies, then ships the code
    assert "Run `make deploy-prod`" not in DEPLOY_COMMAND


def test_deploy_command_ships_the_code_without_applying():
    # Arrange / Act / Assert
    assert "make deploy-code ENV=prod" in DEPLOY_COMMAND


def test_deploy_command_hands_the_apply_to_the_person():
    # Arrange / Act / Assert
    assert "make infra-apply ENV=prod" in DEPLOY_COMMAND
    assert "person" in DEPLOY_COMMAND


def test_deploy_command_mentions_auto_approve_only_to_forbid_it():
    # Arrange
    lines = [line for line in DEPLOY_COMMAND.splitlines() if "-auto-approve" in line]

    # Act / Assert
    assert lines, "the command must name -auto-approve to forbid it"
    assert all("never" in line.lower() for line in lines)
