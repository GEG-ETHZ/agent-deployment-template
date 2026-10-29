# Security Policy

This policy covers the **template repository**: the cookiecutter template, its generation
hooks, and the defaults it writes into every project made from it. Projects generated from
the template ship their own `SECURITY.md` covering their runtime behaviour.

## Reporting a vulnerability

**Do not open a public GitHub issue for anything exploitable.**

Report it privately through
[GitHub Security Advisories](https://github.com/GEG-ETHZ/agent-deployment-template/security/advisories/new).

We aim to respond within 5 business days and to release a fix within 30 days for critical
issues.

## Scope

In scope:

- **The generation hooks.** `hooks/pre_gen_project.py` and `hooks/post_gen_project.py` run
  as Python on the machine of whoever generates a project, and `post_gen_project.py` also
  shells out to `uv` and `git`. Anything that lets template input reach a shell there is a
  vulnerability in this repository.
- **Insecure defaults reaching generated projects.** A weak workflow permission, an
  unpinned action, an over-broad IAM grant or a credential written to a tracked file is in
  scope here even when the damage only appears downstream — every generated project
  inherits it.
- **Credentials committed to this repository.**
- **The GCP bootstrap that the template ships**, `deployment/scripts/setup_gcp.sh`, and the
  deploy workflow that consumes its output.

Out of scope: the behaviour of an agent you build with the template — its prompts,
its tools and its data handling are yours, and the generated project's `SECURITY.md`
describes how to report those.

## What this repository guards, and how

**In generated projects** (the workflows and hooks under `{{cookiecutter.project_slug}}/`):

- `detect-secrets` runs as a pre-commit hook against a committed baseline
- TruffleHog scans the full git history on every push to `main`, pinned to a commit SHA
- CodeQL static analysis runs on every push to `main`
- `pip-audit` runs on every push to `main` and weekly
- Every workflow declares a read-only `GITHUB_TOKEN` and widens scope per job

**In the template repository itself:**

- `detect-secrets`, `detect-private-key` and `check-added-large-files` run as pre-commit
  hooks
- CI lints and type-checks the generation hooks, and `validate-template.yml` generates a
  project from four variable combinations and runs that project's own checks against it

The template repository does **not** run CodeQL, TruffleHog or `pip-audit` on itself. It
has no runtime dependencies of its own, and its scanning story is the hook set above.

## Known issues

Tracked publicly rather than treated as undisclosed:

- [#8](https://github.com/danielvogler/agent-deployment-template/issues/8) —
  `setup_gcp.sh` mints a service-account key on every run and never revokes it. Generated
  projects authenticate to GCP with a long-lived key held as a repository secret. Workload
  Identity Federation is the fix; until then, rotate that key and treat it as a standing
  risk.
- [#23](https://github.com/danielvogler/agent-deployment-template/issues/23) — actions are
  pinned by tag rather than commit SHA, so a compromised or moved tag would execute here.
  No mutable refs remain.

## Credential handling

- `.env` is gitignored in generated projects and `.env.example` ships in its place
- Secrets belong in GitHub repository secrets or Secret Manager, never in a tracked file
- `setup_gcp.sh` does not echo the key it creates, and documents server-side revocation
