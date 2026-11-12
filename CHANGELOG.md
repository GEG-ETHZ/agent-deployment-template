# Changelog

All notable changes to this cookiecutter template are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html) — see
[Template Versioning](AGENTS.md#template-versioning) in `AGENTS.md` for what bumps count as
MAJOR/MINOR/PATCH and how releases are tagged.

## [Unreleased]

### Changed — breaking

- **Generated agents run under their own Agent Identity instead of the shared
  `agent-engine-sa`.** One service account for every agent in a project meant no agent could
  be scoped or revoked on its own, and every log line named the same principal. Each engine
  now has an identity of its own; `infra/agent/main.tf` grants it `cloudtrace.agent` and
  `logging.logWriter`, and model calls come from the Google-managed
  `aiplatform.agentDefaultAccess` grant on the project.

- **OpenTofu creates the engine; `deploy.py` only ships code to it.** `infra/agent/` creates
  the engine with Agent Identity and every IAM grant, keeping its state in
  `gs://<project>-agents-state/<project_slug>/<env>/`. `make deploy-dev` applies OpenTofu,
  updates the engine it created and then health-checks it. `deploy.py` stops when
  `AGENT_ENGINE_RESOURCE_NAME` is unset instead of creating a second engine, and sends the
  local Python version with the code, without which the API builds on 3.10 and cannot install
  google-adk 2.x.

- **`deploy.yml` signs in through Workload Identity Federation instead of the `GCP_SA_KEY`
  secret.** `infra/agent/ci.tf` grants the repository, in one GitHub environment, access to
  its own engine, its own state prefix and its own folder of the shared staging bucket.
  `setup_gcp.sh` no longer creates a service account or mints a key, and
  `AGENT_ENGINE_SERVICE_ACCOUNT` is gone.

- **CI's grants are made per environment, through the `github-oidc` pool.** A grant on the
  repository alone matches a workflow on any branch, with or without an `environment:`, so a
  required reviewer on `prod` never applied to it. The principal is now
  `…/attribute.repository_environment/<org>/<repo>:<env>`, which GitHub only issues after the
  environment's protection rules have passed. The pool must map that attribute.

- **The shared staging and state buckets are managed in `geg-core-infra`.** `setup_gcp.sh`
  checks that they exist and stops, naming each missing one, instead of creating them with
  its own settings.

- **The deployed agent is traced by Agent Engine's built-in telemetry**
  (`GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true`). Agent Identity tokens are
  certificate-bound, and the agent's own Cloud Trace exporter is rejected with 401. Prompt and
  response text is not captured.

### Added

- `make infra-apply`, `make infra-import`, `make infra-test` and `make deploy-code` in
  generated projects; `ci.yml` runs `make infra-test`, offline against a mocked provider.
- The health check retries while new IAM grants propagate (`--attempts`).
- `setup_gcp.sh` checks that the shared staging and state buckets exist, stopping and naming
  each missing one; it creates none.
- CI's staging access is limited to the agent's own folder `<project_slug>/`, and its names
  are validated before they enter the IAM condition.
- `GITHUB_REPOSITORY` is committed in the `Makefile`, rendered from `github_org` and
  `project_slug`, instead of read from the applier's `origin` remote; empty switches CI's
  access off and needs no pool. Edit it if the repository has another name.
- `setup_gcp.sh` warns when the `github-oidc` pool is missing from the project.
- `/deploy` asks the person to run `make infra-apply` and never passes `-auto-approve`; it
  ships the code with `make deploy-code`.
- `validate-template.yml` and `make validate` run the generated project's OpenTofu checks.

### Fixed

- **The pull-request eval can log in, and a grader that cannot is no longer read as a worse
  agent** (#1). promptfoo's `vertex:` grader sent `GOOGLE_API_KEY` to Vertex whenever it was
  set, which Vertex refuses, so every `llm-rubric` case failed ungraded. The grader now sets
  `expressMode: false` and always uses Application Default Credentials. `eval.yml` logs in
  through Workload Identity Federation as a new GitHub environment `eval`, with
  `GOOGLE_GENAI_USE_VERTEXAI=TRUE` and no API key; `infra/agent/eval.tf` grants that principal
  a per-agent custom role with only `aiplatform.endpoints.predict`, plus
  `serviceUsageConsumer`, in the `dev` state only (`EVAL_STATE_ENV=prod` in `.env` moves it).
  It holds nothing on the engine or the buckets. `tests/evals/enforce.py` replaces the
  workflow's inline check. Cases with `graderError` still count against the threshold, so one
  grader quota error is absorbed like any flaky case, but they are reported first, as "could
  not be graded", instead of as agent failures. promptfoo's exit code 100 on a failed case no longer fails the run step first,
  which had skipped that check. `make eval` runs the same check and the same pinned promptfoo
  as CI.
- **`make eval` says what it needs and costs** (#9). It checks its settings before the first
  model call and stops naming what is missing; the docs state the credentials and the calls a
  run makes. `make eval-check`, also part of `make test`, validates `promptfoo.yaml` and every
  dataset line without a key or a model call. An unknown or empty `MODEL_PROVIDER` is caught
  there too; `deployment/config.py` now holds the one list of providers.

### Upgrading an existing project

For the eval fix alone (#1): after `cruft update`, create the GitHub environment `eval` with no
required reviewers and no deployment-branch rule, give it dev's `GOOGLE_CLOUD_PROJECT`,
`GOOGLE_CLOUD_LOCATION` and `GCP_WORKLOAD_IDENTITY_PROVIDER`, run `make infra-apply ENV=dev`,
and delete the repository secret `GOOGLE_API_KEY`. Until then the eval fails at its login
step. The applier needs the right to create custom roles (`roles/iam.roleAdmin` or owner).

For the Agent Identity change:

The engine is re-created, so the agent gets a new resource ID and a new identity. Prerequisites
in the GCP project: a Workload Identity pool `github-oidc` with a provider `github` that maps
`attribute.repository_environment`, and the shared staging and state buckets, private with
uniform bucket-level access (a federated principal's upload fails with 412 otherwise), as
`geg-core-infra` provides them.

1. `cruft update`, then `make setup-gcp ENV=dev` to check that the shared buckets exist.
2. Move every grant the agent relied on through `agent-engine-sa` beyond model, trace and log
   access into a project-owned file such as `infra/agent/data_access.tf` (see "Adding
   permissions for this agent" in the generated `AGENTS.md`). The new identity inherits nothing.
3. `make deploy-dev`. OpenTofu creates the new engine and its grants, then the code is
   shipped to it. Repeat with `ENV=prod`.
4. Set the repository variables `GCP_WORKLOAD_IDENTITY_PROVIDER` (printed by `setup_gcp.sh`)
   and `GOOGLE_CLOUD_PROJECT`; delete the secrets `GCP_SA_KEY` and `GOOGLE_CLOUD_PROJECT`, and
   the variables `AGENT_ENGINE_RESOURCE_NAME` and `AGENT_ENGINE_SERVICE_ACCOUNT`.
5. Point API consumers at the new engine, then delete the old one by hand.
6. Leave `agent-engine-sa` in place while other projects still use it; delete any key file
   minted for it.

## [2.1.0] - 2026-09-24

### Added

- **Dependabot, in both the template and the projects it generates.** Neither had one, so
  nothing tracked uv dependencies, GitHub Actions or pre-commit hook versions. Monthly and
  grouped, with a 7-day cooldown on Python packages; generated projects keep runtime majors
  ungrouped so they arrive one at a time. Security advisories are unaffected by the schedule.

- **`detect-private-key` and `uv-lock` in generated projects' pre-commit hooks.** The lock
  file is committed and written by `uv sync` during generation, but nothing kept it in step
  with `pyproject.toml` afterwards.

- **A `cruft-update` job in `validate-template.yml`.** It generates a project with
  `cruft create`, commits a template change and requires `cruft update` to apply it, so the
  update path can no longer break unnoticed.

- **A test for the pickle-time import boundary.** `tests/unit/test_pickle_boundary.py`
  unpickles `root_agent` in a fresh interpreter that cannot import `deployment` or `tests`,
  as in the Agent Engine container. A `deployment` import under `agent/` used to deploy green
  and fail on the first request; it now fails CI.

### Fixed

- **`deploy.yml` deployed commits that failed CI.** It ran on every push to `main` in parallel
  with `ci.yml`, so a commit failing lint or tests still reached prod. It now runs on
  `workflow_run` after `ci.yml` succeeds for a push to `main`, deploys the commit CI tested,
  skips a commit that is no longer the tip of `main` (an old run re-run, or runs finishing out
  of order) and queues deploys per environment. Manual `workflow_dispatch` deploys are
  unchanged.

- **The deployed container resolved newer packages than the agent was pickled against.**
  `deploy.py` installed a hand-written list of version floors; `google-adk>=1.0.0` once
  unpickled a 2.2.0 agent under 2.9.2 and every request failed. It now exports exact pins for
  every runtime dependency from `uv.lock`, cloudpickle included.

- **The smoke test missed broken sessions.** It queried without a session, which created one
  inside the same request, so it passed while the console playground hung. The post-deploy
  check and `make health-check` now create a session first, then query it.

- **`cruft update` crashed on every generated project** with `ChangesetUnicodeError`. Cruft
  runs the post-gen hook on both copies it renders, giving each a `.git` and a `.venv` whose
  binary diff it cannot decode. The generated `pyproject.toml` now sets
  `[tool.cruft] skip = [".venv", ".git", "uv.lock"]`.

  **Existing projects:** cruft reads `skip` before it diffs, so this cannot arrive through
  `cruft update` alone. Add `"skip": [".venv", ".git", "uv.lock"]` to `.cruft.json`, commit,
  then update. Not to `pyproject.toml`: the update adds that section itself, and a second copy
  becomes a duplicate table that breaks the TOML.

- **`adk web` session data could be committed.** The generated `.gitignore` now ignores
  `.adk/`, where `make dev` stores every local conversation event, including tool arguments
  and the data tools returned. **Existing projects:** run `git rm --cached -r agent/.adk` once.

### Security

- **Generated projects no longer run unpinned third-party code.** `security.yml` followed
  `trufflesecurity/trufflehog@main` and `eval.yml` ran `promptfoo@latest`; both resolved at
  run time, so whatever was published under that ref executed with repository read access.
  TruffleHog is now pinned to a commit SHA *and* to an exact scanner image tag — the action
  is a wrapper around `docker run`, so the SHA alone would still have pulled `:latest` —
  and promptfoo to an exact version.

- **Every workflow now declares a read-only `GITHUB_TOKEN`.** Only `lint-pr.yml` set
  `permissions`, so the other workflows in both layers inherited the organisation default
  — a setting held outside the repo and changeable without a commit. Where that default is
  read-and-write, those jobs held a token that could push commits. `security.yml`'s
  job-level scopes are unchanged; `deploy.yml` notes the `id-token: write` a future move to
  Workload Identity Federation will need.

### Documentation

- Node.js 22+ is now the documented prerequisite. promptfoo refuses to start below 22.22, so
  the old "20+" could not run `make eval`.
- `anthropic`, `openai` and key-based `litellm` providers fail on every request once deployed,
  because their API keys are not forwarded to Agent Engine. This is now stated where the
  providers are introduced.
- The Pyright badge claimed strict mode; both `pyproject.toml` files run it in basic mode.

## [2.0.0] - 2026-09-17

### Changed

- **BREAKING: deployed agents now run as `agent-engine-sa`, not the project's shared Reasoning
  Engine Service Agent.** `deploy.py` now always passes a `service_account`, where before it
  passed none, so the next deploy after a `cruft update` fails with `PermissionDenied` on
  `actAs` until the new IAM binding exists.

  **Migration:** re-run `make setup-gcp ENV=<env>` before the next deploy — it adds the binding
  and is safe to re-run. Then check that `agent-engine-sa` holds whatever roles the agent needs
  at runtime, because the identity it runs under genuinely changes. To defer, pin the template
  to the previous release rather than updating.

- **Retracted: "the observability layer has no destination in production."** An earlier draft
  claimed Agent Engine did not forward container stdout, and added a `google-cloud-logging`
  handler to compensate. The diagnosis was wrong: stdout is forwarded, and the missing logs came
  from a disabled `_Default` sink in the GCP project. The handler and its dependency are gone.
  See "Things that will bite you" in `AGENTS.md`.

### Fixed

- `.env.example` was excluded by the generated `.gitignore`'s `.env.*` rule, so the initial
  commit never tracked it and `cp .env.example .env` failed for anyone cloning.
- Generated projects ignored their chosen Python version: `requires-python` set only a floor, so
  `uv sync` took the newest interpreter installed. A `.python-version` file now pins it.
- Local development could not use Application Default Credentials. Nothing set
  `GOOGLE_GENAI_USE_VERTEXAI`, so google-genai used the AI Studio backend and demanded an API
  key even with valid ADC. It now defaults to `TRUE` in `.env.example`.
- `read_traces.py` read `GOOGLE_CLOUD_PROJECT` from the environment but never loaded `.env`,
  then reported "Set GOOGLE_CLOUD_PROJECT in .env" — naming a file it had not read.
- `.cruft.json` could be written with an empty `commit` when generating from a relative path,
  which made a later `cruft check` abort instead of reporting drift.
- `setup_gcp.sh` printed the service-account private key to stdout. It now pipes the value into
  `gh secret set` without rendering it, and documents server-side revocation.
- `make logs` and `make traces` queried the wrong things, and tracing never worked at all.
  `read_logs.sh` filtered on a resource type Agent Engine does not use; `read_traces.sh` printed
  a Cloud Logging filter labelled as a Cloud Trace filter and never called an API. No exporter
  had ever been configured, so `@instrument` produced no spans. Replaced by a unit-tested
  `read_traces.py` against the Cloud Trace v1 API.
- `make setup-monitoring` could not be re-run: the second run failed with "Update Dashboard
  should specify a non empty etag". The script now reads the live etag and injects it.
- Local deploys need `gcloud auth application-default login` as well as `gcloud auth login`,
  and no generated doc said so. The failure arrives after the agent is pickled and uploaded.
- A renamed staging bucket was silently ignored in CI: `setup_gcp.sh` printed
  `GCS_STAGING_BUCKET` as an environment variable while `deploy.yml` read it from `secrets`.
- `cruft create` left every generated project with a dirty working tree, because the post-gen
  hook committed `.cruft.json` before cruft rewrote the same file.
- Generation failed outright on any machine without a configured git identity, and because
  cookiecutter treats a failing post-gen hook as fatal, no project was left behind.
- `hooks/post_gen_project.py` ran `git init` and `git add -A` but never committed, and the
  first fix for that had its own bug.
- `security.yml`'s CodeQL job failed permanently on private repositories without Advanced
  Security. It now probes the API and skips when code scanning is unavailable.
- Generating with `python_version=3.12` produced a project that failed its own `ruff check`.
- Six template source files were not `ruff format` clean, so generated projects failed CI.
- Freshly generated projects failed their own `make pre-commit` before their author had
  written a line.
- Generated `ci.yml` enforced the project-wide coverage gate against each suite separately,
  which neither was meant to clear alone. A `coverage` job now runs them together.
- Generated `eval.yml` pinned Node 20, passed `--ci` (not a recognised flag), and gated on
  promptfoo's exit code, which is `0` even when every case errors. It now parses `output.json`
  and fails on any error or a pass rate below the configured threshold. The eval job likely
  never actually worked in any generated project until this change.
- Generated `README.md` and `CLAUDE.md` documented the wrong default for
  `GOOGLE_CLOUD_LOCATION`.
- Three real make targets were undocumented: `make test-integration`, `make clean` and
  `make help`.

### Added

- Core observability library `agent/observability.py`: structured JSON logging, `@instrument`,
  `log_event` and `redact_pii`, with `severity` and `agent_name` on every event so entries are
  queryable in Cloud Logging rather than plain text.
- Cloud Trace export, enabled per deployment by `CLOUD_TRACE_ENABLED`, off by default so a
  local `make dev` stays offline.
- Cloud Monitoring dashboard and two alert policies under `deployment/monitoring/`, with
  `setup_monitoring.sh` to install them.
- Rollback support: `deploy.yml` accepts an optional `ref`, and `make rollback REF=<tag>`
  redeploys a previous ref against the existing Agent Engine resource.
- Standalone health check at `deployment/scripts/health_check.py`, runnable against an
  already-deployed resource rather than only as part of a deploy.
- cruft integration so generated projects track the template, plus a drift-detection CI job.
- Testing infrastructure: mocked integration tests and skill-segmented promptfoo evals.
- Coverage now measures `deployment/` as well as `agent/`, with new unit tests for the deploy
  path, `check_resource` and `deployment/config.py`.
- `validate-template.yml` generates four cookiecutter variants instead of one, and also runs
  `ruff format --check` and the generated project's own pre-commit set.
- Conventional-commit enforcement on PR titles in generated projects (`lint-pr.yml`), which
  matters because a squash merge uses the PR title as the commit subject.
- Documented dev/prod environment separation, with a required GitHub Environments table.

## [1.1.0] - 2026-07-20

> **Not tagged.** `v1.0.0` and `v1.1.0` were recorded here but never pushed as git tags, so
> `cruft update --checkout v1.1.0` cannot resolve. `v2.0.0` is the first release with a tag;
> pin to that or later. The two sections below are kept as a record of what changed.

First cruft-aware release: generated projects can now track and pull in template updates
via `cruft check`/`cruft update` instead of only being generated once and left to drift.

### Fixed

- `hooks/post_gen_project.py` no longer crashes under `cruft create`/`cruft update`: those
  commands only inject `_template`/`_commit` into the cookiecutter context (not
  `_repo_dir`/`_checkout`, which plain `cookiecutter` provides), and the strict Jinja lookup
  raised `UndefinedError` and aborted generation. All private context lookups now use a
  Jinja `default` so both flows work.

### Added

- Template repo: `cruft` dev dependency for template maintainers to test `cruft create`/`cruft update`
- Generated repo: `.cruft.json` auto-generated by `hooks/post_gen_project.py`, pinning the exact
  template commit used so `cruft check`/`cruft update` can track drift later
- README: documented `cruft create` as the canonical project generation method, with a
  "keeping in sync" section covering `cruft check`/`cruft update`
- Generated repo: `cruft-check.yml` workflow — non-blocking drift check that warns when the
  project has fallen behind the template (`cruft check` on push/PR/weekly schedule)
- Template versioning discipline documented in `CLAUDE.md`, so releases are tagged and
  generated projects have a controlled `cruft update --checkout <tag>` upgrade path

## [1.0.0] - 2026-07-20

Initial template baseline, tagged retroactively as the `1.0.0` reference point that
`1.1.0` and later releases version against. No `v1.0.0` git tag exists — only `v1.1.0`
onward are tagged (see [Template Versioning](CLAUDE.md#template-versioning)).

### Added

- Initial cookiecutter template with full ADK agent scaffold
- `cookiecutter.json` with project metadata and model provider selection
- `hooks/pre_gen_project.py` — input validation before generation
- `hooks/post_gen_project.py` — git init, uv sync, pre-commit install after generation
- Generated repo: Google ADK `root_agent` with `get_current_datetime` and `web_search` tools
- Generated repo: `prompts/` directory with YAML registry for prompt composition
- Generated repo: `deployment/` with Agent Engine deploy script and GCP bootstrap scripts
- Generated repo: `tests/unit/` with tool and model tests
- Generated repo: `tests/evals/` with promptfoo red-team configuration
- Generated repo: GitHub Actions CI, security, eval, and deploy workflows
- Generated repo: `CLAUDE.md` with full developer and AI assistant instructions
- Generated repo: `.claude/commands/` with `/deploy`, `/eval`, `/logs` slash commands
- Template repo: `ci.yml`, `validate-template.yml`, `lint-pr.yml` workflows
- Template repo: `CLAUDE.md` with template contribution instructions
