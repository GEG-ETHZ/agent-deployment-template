import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(os.path.realpath(os.path.curdir))
LICENSE_CHOICE = "{{ cookiecutter.open_source_license }}"
PROJECT_SLUG = "{{ cookiecutter.project_slug }}"
AUTHOR_NAME = "{{ cookiecutter.author_name }}"
AUTHOR_EMAIL = "{{ cookiecutter.author_email }}"

# Plain `cookiecutter` injects _template/_repo_dir/_checkout into the context.
# `cruft create`/`cruft update` instead inject _template/_commit and omit the
# rest, so every lookup here needs a Jinja default to avoid a hard failure.
TEMPLATE_URL = "{{ cookiecutter._template | default('') }}"
TEMPLATE_REPO_DIR = "{{ cookiecutter._repo_dir | default('') }}"
TEMPLATE_CHECKOUT = "{{ cookiecutter._checkout | default('') }}"
TEMPLATE_COMMIT_HINT = "{{ cookiecutter._commit | default('') }}"

CRUFT_CONTEXT = {
    "project_name": "{{ cookiecutter.project_name }}",
    "project_slug": "{{ cookiecutter.project_slug }}",
    "project_description": "{{ cookiecutter.project_description }}",
    "author_name": "{{ cookiecutter.author_name }}",
    "author_email": "{{ cookiecutter.author_email }}",
    "github_org": "{{ cookiecutter.github_org }}",
    "gcp_project_id": "{{ cookiecutter.gcp_project_id }}",
    "gcp_location": "{{ cookiecutter.gcp_location }}",
    "model_provider": "{{ cookiecutter.model_provider }}",
    "python_version": "{{ cookiecutter.python_version }}",
    "open_source_license": "{{ cookiecutter.open_source_license }}",
    "_template": TEMPLATE_URL,
}

# `cruft create` rewrites .cruft.json itself after this hook has already committed it,
# appending _commit to the context (see cruft's generate_cookiecutter_context). Without
# the same key here, that rewrite differs from what we committed and every project made
# the documented way starts with a dirty working tree. Only cruft supplies _commit, so
# plain-cookiecutter runs correctly omit it.
if TEMPLATE_COMMIT_HINT:
    CRUFT_CONTEXT["_commit"] = TEMPLATE_COMMIT_HINT


def run(cmd: str, check: bool = True) -> int:
    result = subprocess.run(cmd, shell=True, cwd=PROJECT_DIR)
    if check and result.returncode != 0:
        sys.exit(result.returncode)
    return result.returncode


def remove_file(relative_path: str) -> None:
    target = PROJECT_DIR / relative_path
    if target.exists():
        target.unlink()


def uv_available() -> bool:
    return subprocess.run("which uv", shell=True, capture_output=True).returncode == 0


def ensure_git_identity() -> None:
    """Give the new repo a committer identity if the machine has none.

    `git commit` exits 128 with "empty ident name" wherever no identity is
    configured and git cannot guess one from the OS user — CI runners,
    containers, freshly-imaged laptops. That aborted generation outright and
    left no project behind at all, since cookiecutter treats a failing
    post-gen hook as fatal.

    An identity already configured (global or system) is left alone; the
    fallback is written to the new repo's local config only, so nothing
    outside it is touched. Argument lists rather than a shell string, because
    an author name may contain quotes.
    """
    for key, fallback in (("user.name", AUTHOR_NAME), ("user.email", AUTHOR_EMAIL)):
        existing = subprocess.run(
            ["git", "config", "--get", key],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
        )
        if existing.returncode == 0 and existing.stdout.strip():
            continue
        subprocess.run(["git", "config", key, fallback], cwd=PROJECT_DIR, check=False)


def get_template_commit() -> str:
    if TEMPLATE_COMMIT_HINT:
        return TEMPLATE_COMMIT_HINT
    if not TEMPLATE_REPO_DIR:
        return ""
    result = subprocess.run(
        "git rev-parse HEAD",
        shell=True,
        cwd=TEMPLATE_REPO_DIR,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def write_cruft_json() -> None:
    """Write .cruft.json, or skip it when the template commit cannot be determined.

    Cookiecutter chdirs into the generated project before running this hook, so a
    relative `_repo_dir` -- what `cookiecutter .` passes, which is exactly what
    `make validate` runs -- no longer resolves to the template. `git rev-parse` then
    returns nothing and the file gets `"commit": ""`, which makes a later
    `cruft check` die with `BadName: Ref '' did not resolve to an object` rather than
    reporting drift. A relative `"template"` is equally useless to `cruft update`,
    which runs from the generated project, not from where cookiecutter was invoked.

    So: write the file only when it would actually work, and say so when it would not.
    Generating from a URL or an absolute path -- the documented paths -- is unaffected.
    """
    commit = get_template_commit()
    template_is_usable = bool(TEMPLATE_URL) and (
        "://" in TEMPLATE_URL
        or TEMPLATE_URL.startswith(("gh:", "gl:", "bb:", "git@"))
        or os.path.isabs(TEMPLATE_URL)
    )
    if not commit or not template_is_usable:
        print(
            "\nNOTE: skipping .cruft.json — the template was generated from a\n"
            "relative path, which cruft cannot resolve later. Template update\n"
            "tracking is off.\n"
            "To enable it, regenerate from a URL or an absolute path, or run:\n"
            "  cruft link <template-url>"
        )
        return

    cruft_config = {
        "template": TEMPLATE_URL,
        "commit": commit,
        "checkout": TEMPLATE_CHECKOUT
        if TEMPLATE_CHECKOUT not in ("", "None")
        else None,
        "context": {"cookiecutter": CRUFT_CONTEXT},
        "directory": None,
    }
    cruft_json = PROJECT_DIR / ".cruft.json"
    # Mirrors cruft's own json_dumps: ensure_ascii=False matters for a non-ASCII
    # author name, which would otherwise be escaped here and unescaped by cruft.
    cruft_json.write_text(json.dumps(cruft_config, ensure_ascii=False, indent=2) + "\n")


# Remove license file for proprietary projects
if LICENSE_CHOICE == "Proprietary":
    remove_file("LICENSE")

# Track the template commit so `cruft check`/`cruft update` work later,
# even for projects generated via plain `cookiecutter` rather than `cruft create`.
print("\n> Recording template version in .cruft.json...")
write_cruft_json()

# Initialise git
print("\n> Initialising git repository...")
run("git init")

# Run uv sync before the initial commit below, not after — it writes uv.lock, and
# .gitignore deliberately does NOT exclude uv.lock (it's meant to be committed). Syncing
# first means `git add -A` below actually picks it up, instead of leaving it untracked.
if uv_available():
    print("\n> Installing dependencies with uv...")
    run("uv sync")
else:
    print(
        "\nWARNING: uv not found. Install from https://docs.astral.sh/uv/ then run:\n"
        "  uv sync\n"
        "  uv run pre-commit install\n"
        "  uv run pre-commit install --hook-type commit-msg"
    )

run("git add -A")
# Commit before installing pre-commit hooks below, so this initial commit isn't subject
# to hook enforcement (autofixes from ruff/markdownlint would otherwise block it).
ensure_git_identity()
INITIAL_COMMIT_MSG = "chore: initial commit from agent-deployment-template"
# Non-fatal on purpose: a project that generated but did not commit is
# recoverable in one command, whereas a failing hook makes cookiecutter delete
# everything it just produced.
if run(f'git commit -m "{INITIAL_COMMIT_MSG}"', check=False):
    print(
        "\nWARNING: the initial commit failed. The project is generated and\n"
        "every file is staged — finish it with:\n"
        f'  git -C {PROJECT_SLUG} commit -m "{INITIAL_COMMIT_MSG}"'
    )

if uv_available():
    print("\n> Installing pre-commit hooks...")
    run("uv run pre-commit install")
    run("uv run pre-commit install --hook-type commit-msg")

print(
    f"""
{"=" * 60}
 Agent repository created: {PROJECT_SLUG}
{"=" * 60}

Next steps:
  1. cd {PROJECT_SLUG}
  2. cp .env.example .env
  3. Fill in API keys and GCP settings in .env
  4. make dev          # run the agent locally at http://localhost:8000
  5. make test         # run unit and integration tests
  6. make setup-gcp    # one-time GCP bootstrap (when ready to deploy)
  7. make deploy-dev   # deploy to Agent Engine (dev)

See README.md and AGENTS.md for full documentation.
"""
)
