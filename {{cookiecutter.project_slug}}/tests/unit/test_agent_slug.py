"""The Makefile's AGENT_SLUG and the staging folder name must be the same string.

CI's staging grant (infra/agent/ci.tf) allows writes under `<AGENT_SLUG>/` only, while
deploy.py uploads under the project name from pyproject.toml. If they differ, every CI
deploy fails with a 403 on upload.
"""

import re
from pathlib import Path

from deployment.config import DeploymentConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_SLUG_LINE = re.compile(r"^AGENT_SLUG\s*:?=\s*(\S+)\s*$", re.MULTILINE)


def test_makefile_agent_slug_is_the_staging_folder(monkeypatch):
    # Arrange
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    makefile = (REPO_ROOT / "Makefile").read_text()

    # Act
    match = AGENT_SLUG_LINE.search(makefile)
    staging_folder = DeploymentConfig.from_env().gcs_dir_name

    # Assert
    assert match is not None, "Makefile defines no AGENT_SLUG"
    assert match.group(1) == staging_folder
