"""setup_gcp.sh checks the shared buckets and never creates them.

The staging and state buckets are shared by every agent of the project and managed in
geg-core-infra. A script that created them would give each agent's own settings to a bucket
all agents depend on. The script runs here against a fake `gcloud` on the PATH, so nothing
reaches GCP.
"""

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "deployment" / "scripts" / "setup_gcp.sh"
PROJECT = "test-project"
STAGING = f"{PROJECT}-agent-staging"
STATE = f"{PROJECT}-agents-state"

FAKE_GCLOUD = """#!/usr/bin/env bash
echo "$@" >> "$FAKE_GCLOUD_LOG"
case "$*" in
  "storage buckets describe "*)
    bucket="${4#gs://}"
    for existing in $EXISTING_BUCKETS; do
      [ "$existing" = "$bucket" ] && exit 0
    done
    exit 1
    ;;
  "projects describe "*) echo 123456789 ;;
esac
exit 0
"""


def _run_setup(tmp_path: Path, existing_buckets: list[str], environment: str = "dev"):
    """Run the script with a fake gcloud; return the process and the gcloud calls."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gcloud = bin_dir / "gcloud"
    gcloud.write_text(FAKE_GCLOUD)
    gcloud.chmod(0o755)
    log = tmp_path / "gcloud.log"
    log.touch()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GOOGLE_CLOUD_PROJECT": PROJECT,
        "FAKE_GCLOUD_LOG": str(log),
        "EXISTING_BUCKETS": " ".join(existing_buckets),
    }
    env.pop("GCS_STAGING_BUCKET", None)
    env.pop("STATE_BUCKET", None)
    result = subprocess.run(
        ["bash", str(SCRIPT), environment],
        env=env,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    return result, log.read_text().splitlines()


def test_succeeds_when_both_shared_buckets_exist(tmp_path):
    # Arrange / Act
    result, _ = _run_setup(tmp_path, [STAGING, STATE])

    # Assert
    assert result.returncode == 0, result.stdout + result.stderr


def test_never_creates_or_changes_a_bucket(tmp_path):
    # Arrange / Act: with nothing existing, a creating script would call `buckets create`
    _, calls = _run_setup(tmp_path, [])

    # Assert
    assert not any(
        "buckets create" in call or "buckets update" in call for call in calls
    )


def test_dev_names_the_eval_environment_without_reviewers(tmp_path):
    # Arrange / Act
    result, _ = _run_setup(tmp_path, [STAGING, STATE])

    # Assert: a reviewer or a main-only branch rule would block every pull request's eval
    output = result.stdout
    assert "environment named 'eval'" in output
    assert "NO required reviewers and NO deployment-branch rule" in output


def test_prod_also_names_the_eval_environment_and_how_to_grant_it(tmp_path):
    # Arrange / Act: a project without dev learns about the eval from its prod setup
    result, _ = _run_setup(tmp_path, [STAGING, STATE], environment="prod")

    # Assert
    output = result.stdout
    assert "environment named 'eval'" in output
    assert "EVAL_STATE_ENV=prod in .env" in output


def _missing_lines(output: str) -> list[str]:
    return [
        line.strip()
        for line in output.splitlines()
        if line.strip().startswith("missing:")
    ]


def test_fails_naming_the_missing_bucket_and_where_it_is_managed(tmp_path):
    # Arrange / Act
    result, _ = _run_setup(tmp_path, [STATE])

    # Assert: only the bucket that is absent is named
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert _missing_lines(output) == [f"missing: gs://{STAGING}"]
    assert "geg-core-infra" in output


def test_reports_every_missing_bucket_at_once(tmp_path):
    # Arrange / Act
    result, _ = _run_setup(tmp_path, [])

    # Assert
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert _missing_lines(output) == [
        f"missing: gs://{STAGING}",
        f"missing: gs://{STATE}",
    ]
