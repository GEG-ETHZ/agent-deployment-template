# Validation Runbook — how to validate this template

How to prove the template repo is healthy, how to prove a generated project actually deploys
to Vertex AI Agent Engine, and how to move an existing agent into it. This is a **runbook**:
re-run the relevant section whenever `{{cookiecutter.project_slug}}/` changes.

---

## GCP gotchas — each of these costs real time if you don't know it up front

- **Read the agent's identity from `spec.effective_identity`.** OpenTofu exposes it as
  `google_vertex_ai_reasoning_engine.agent.spec[0].effective_identity` and `make infra-apply`
  prints it as `agent_principal`. It changes whenever the engine is re-created, so anything
  that replaces the engine (a new `region`, a `tofu destroy`) also drops every grant made to
  the old principal.
- **Model calls work without a grant you made.** Google grants
  `roles/aiplatform.agentDefaultAccess` to every agent identity of the project
  (`principalSet://…/attribute.platformContainer/aiplatform/projects/<number>`) once the first
  Agent Identity engine exists. Look for it in the project IAM policy before concluding a
  grant in `infra/agent/` is missing.
- **Agent Identity tokens are certificate-bound.** A client that cannot do mTLS gets
  401 UNAUTHENTICATED, which is why the agent's own Cloud Trace exporter is off and Agent
  Engine's built-in telemetry (`GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true`) records
  the traces instead.
- **The SDK's `update()` never sends `python_version`.** On an engine OpenTofu created, the
  API then defaults to 3.10 and the container build fails on google-adk 2.x
  (`No matching distribution found`). `deployment/python_version.py` adds it; a build log
  showing Python 3.10 means that wrapper is not in effect.
- **Workload Identity Federation needs uniform bucket-level access.** A federated principal
  cannot write to a bucket with fine-grained ACLs: the upload fails with 412. Check with
  `gcloud storage buckets describe gs://<bucket> --format='value(uniform_bucket_level_access)'`.
- **One update at a time per engine.** A second deploy while the first is still building
  fails with `FAILED_PRECONDITION … Current state: UPDATING`. Wait for the operation, do not
  retry in a loop.
- **Check a log sink's `disabled` flag, not just its filter.**
  `gcloud logging sinks describe _Default --format='value(disabled)'`. A disabled `_Default`
  discards every non-audit entry however written, including a direct `gcloud logging write`,
  and looks exactly like broken instrumentation. Note `gcloud logging exclusions` is **not a
  valid subcommand** in this CLI version, so an exclusions check can error in a way that reads
  as "none found".
- **Sink changes take several minutes to propagate, and entries written meanwhile are lost.**
  This produces false negatives. Write a canary and poll for it before concluding anything.
- **`gsutil -m rm` hangs on macOS** (its own output warns: bugs.python.org/issue33725). The
  deletes complete but the process never exits. Use `gcloud storage rm -r`, or drop `-m`. Do
  not conclude the deletes failed — verify with `ls` after interrupting.
- **Tool spans are *children* of ADK's `invoke_workflow` root span**, so a `view=ROOTSPAN`
  trace listing never shows them. `read_traces.py --spans` expands them; `--filter
  "span:<tool>"` selects traces containing one.
- **The requirements warning is non-deterministic** — one deploy can report a different
  missing-package count than another for identical code. Only `cloudpickle` is auto-appended;
  the rest are satisfied transitively.
- **ADC is a separate credential store from the CLI login.** `gcloud auth login` does **not**
  refresh Application Default Credentials — `vertexai.init()` reads ADC, so a local deploy also
  needs `gcloud auth application-default login`; skipping it surfaces mid-deploy as a
  `RefreshError`. Both stores go stale independently, so check both before deploying:
  `gcloud auth print-access-token` and `gcloud auth application-default print-access-token`.

## Deploy/teardown recipe that works (no `.env` juggling)

The staging and state buckets are derived from the project id, and the engine name comes from
the OpenTofu state, so a deploy needs one line of `.env`:

```bash
echo GOOGLE_CLOUD_PROJECT=example-gcp-project > .env
make deploy-dev   # OpenTofu creates or keeps the engine, then the code is shipped to it
```

Teardown: OpenTofu removes the engine together with every grant made to its identity.
`make -n infra-apply ENV=dev` prints the `-var` flags; run the same command with `destroy`:

```bash
make infra-init ENV=dev
tofu -chdir=infra/agent destroy <the -var flags make -n infra-apply printed>
gcloud storage rm -r "gs://example-gcp-project-agent-staging/<agent-slug>/"   # NEVER the bucket root
gcloud monitoring dashboards delete <id> --project=example-gcp-project --quiet
gcloud monitoring policies delete "projects/example-gcp-project/alertPolicies/<id>" --project=example-gcp-project --quiet
```

`gcloud monitoring policies delete` takes **one policy per invocation** — passing two prints
help and silently does nothing.

## Notes for whoever (or whichever agent) picks this up

- **An AI coding agent working in this repo is typically denied `rm`, `curl`,
  `git commit`, `git push`, and `Read`/`Write` on `.env*`** (including `.env.example`), by
  design. Practical effects: teardown deletions, version lookups, `.env` edits, and commits are
  always a manual step for a human. The `.env*` denial also silently strips matches from a
  recursive `grep` run through such an agent's shell tool, with no error — never conclude
  "nothing references X" from a grep that could have hit `.env*`.
- **Validate commit messages before committing:** `uv run cz check --commit-msg-file <file>`.
  The commit-msg hook runs commitizen. Accepted types are the 12 from
  `cz_conventional_commits`.
- **`uv --directory` sets the working directory**, so a generated project lands wherever that
  points rather than where you ran the command. Use `--output-dir` with an absolute path, or
  `cd` into the target first and check `pwd`.
- **`gcloud alpha` is not installed** in a typical environment, so monitoring
  channels/policies must be queried through the REST API. See §3 for working
  `AuthorizedSession` snippets.
- **Generate with `cookiecutter .` when testing uncommitted template changes.** `cruft create
  <github-url>` fetches the *pushed* branch, so it would silently test the old code — the
  opposite of what you want, unless the test specifically involves GitHub CI (see below).
- **A stale `cd` after regenerating a scratch project is a real hazard.** Moving the old
  project aside leaves the terminal inside the moved directory, so `make deploy-dev` would
  deploy pre-change code. Re-`cd` to the absolute path and check `pwd` first.

## How to test CI without waiting on the fork — reusable technique

GitHub disables workflows on forks until someone clicks *"I understand my workflows, go ahead
and enable them"* in the Actions tab, and there is no REST endpoint for that button. The API
is actively misleading: `actions/permissions` reports `"enabled": true` and every workflow
shows `active`, while `actions/runs` returns `total_count: 0` — zero runs, ever.

**A freshly created repo is not a fork, so its workflows run on the first push.** That
sidesteps the button entirely. Two scratch repos cover the two distinct workflow sets, which
barely overlap:

| Workflow | Template repo | Generated project |
| --- | --- | --- |
| `ci.yml` | ✓ lints `hooks/` | ✓ 4 jobs, different file |
| `lint-pr.yml` | ✓ | ✓ |
| `validate-template.yml` | ✓ | ✗ **does not exist** |
| `eval.yml`, `cruft-check.yml`, `deploy.yml`, `security.yml` | ✗ | ✓ |

So a generated dummy can never exercise `validate-template.yml`. To test it, push a *copy of
the template repo* to a fresh non-fork repo.

```bash
# template-repo CI
git clone /path/to/agent-deployment-template /tmp/ci-template
cd /tmp/ci-template && git remote remove origin
gh repo create adk-template-ci-check --private --source=. --push

# generated-project CI — use cruft, not cookiecutter (see below)
cd /tmp && uv --directory /path/to/agent-deployment-template run \
  cruft create https://github.com/philippschaedle/agent-deployment-template \
  --no-input -y --extra-context '{"project_name":"Ci Check Agent"}'
```

**`uv --directory` sets the working directory**, so the generated project lands in the
template repo, not where you ran the command — `cd` into the target and use an absolute
`--directory`, or just move the result afterwards.

**Generate with `cruft create <url>`, not `cookiecutter .`**, whenever a test involves
GitHub. Plain cookiecutter writes `"template": "."` and an empty `commit`, which CI cannot
resolve, and it hides two real bugs that only the cruft path exhibits (the `detect-secrets`
`.cruft.json` finding and a dirty tree).

`lint-pr.yml`, `eval.yml` and `cruft-check.yml` are `pull_request`-only — a push to `main`
will not fire them. Open a PR in the scratch repo to exercise them, and note `gh pr checks`
needs the PR number when `--repo` is given: `gh pr checks 1 --repo <owner/repo> --watch`.

---

## 1. Commands to run (fully automated)

Run these in order. Each one gates the next — don't skip ahead if one fails.

### 1a. Template repo itself

```bash
make install       # uv sync (dev deps for hooks/) + installs the pre-commit and
                    # commit-msg git hooks — easy to forget in a fresh clone,
                    # and nothing runs on commit until they are installed
make lint           # ruff check hooks/
make format          # ruff format hooks/ (then re-run lint if it changed anything)
make typecheck      # pyright hooks/
make pre-commit     # every pre-commit hook, all files
```

Note the *template repo's* hook set is deliberately leaner than the generated project's:
ruff, ruff-format, check-yaml, check-json, end-of-file-fixer, trailing-whitespace,
check-merge-conflict, markdownlint-cli2, plus commitizen at the `commit-msg` stage. The
generated project additionally runs pyright, detect-secrets, check-toml and
check-added-large-files (see `{{cookiecutter.project_slug}}/.pre-commit-config.yaml`) —
don't expect those to fire here. `pyright` is covered by `make typecheck` instead.

### 1b. Full template → generated-project validation

```bash
make validate
```

This is the one command that matters most before a PR — it's exactly what `ci.yml` and
`validate-template.yml` run in CI. It generates a throwaway project into `/tmp/cc-validate`,
runs `uv sync --frozen`, `ruff check .`, `ruff format --check .`, `pytest tests/unit`, and
`pytest tests/integration` inside it, then deletes it. If this passes locally, CI will
almost certainly pass too — run it before pushing, not after.

**Know what it still doesn't cover, because this is where bugs hide.** `make validate` runs
neither `pyright`, nor `tests/evals`, nor the generated project's own `pre-commit` hook set,
and it only ever generates the **default** cookiecutter variant. Bugs have repeatedly lived in
exactly that blind spot. CI's `validate-template.yml` now covers the pre-commit hooks and four
variants; locally, 1c and 1d below are what close the gap.

Note also that ruff can never be run against the template sources in place —
`{{cookiecutter.project_slug}}/pyproject.toml` has unrendered Jinja in `requires-python`, so
ruff aborts with `Failed to parse version: >={{cookiecutter.python_version}}`. Anything that
lints or formats the generated tree *must* go through a rendered project. If you ever need to
format a template source by hand, use `ruff format --isolated --line-length 88
--target-version py311 <file>`, then confirm the result against a fresh generation — a
cookiecutter substitution changes a line's length, so template source and rendered source can
legitimately format differently. Keep length-sensitive Jinja off assertion lines (bind it to a
variable first, as `tests/unit/test_config.py` does).

### 1c. Manually generate once and drive it directly

Rather than relying only on `make validate`'s temp-dir-and-delete cycle, generate one
persistent copy so you can poke at it in the following sections:

```bash
rm -rf /tmp/agent-test
cookiecutter . --no-input \
  --output-dir /tmp/agent-test \
  project_name="Test Agent" \
  author_email="you@example.com" \
  gcp_project_id="<a real or throwaway GCP project id>"
cd /tmp/agent-test/test-agent

make install
make lint
make typecheck        # pyright, generated project — not covered by `make validate`
make test              # unit + integration, with coverage
make eval              # promptfoo — needs GOOGLE_API_KEY (or the provider set in .env) exported
make pre-commit
```

`make eval` needs an API key for whichever `MODEL_PROVIDER` you generated with (default
`google` → `GOOGLE_API_KEY`). If you don't want to spend a key on this pass, skip it here —
it's exercised again in Phase 2 below regardless, and CI's `eval.yml` gates PRs to
generated repos, not this one.

**Why this matters:** `make pre-commit` on a freshly generated project is what catches bugs
`make validate` alone won't — a freshly generated project failing its own hook set is a real,
recurring failure mode, not a hypothetical. Always run it against a fresh generation, not just
inside `make validate`'s throwaway copy.

### 1d. Cookiecutter variant matrix (commands, still automated per-variant)

The `make validate` / manual-generate paths above use the defaults (`model_provider=google`,
`python_version` default, `open_source_license` default). Cookiecutter choice variables are
a combinatorial surface that a single default run doesn't cover. At minimum, repeat 1c's
`make install && make lint && make typecheck && make test` for:

- [ ] `model_provider=anthropic` and `model_provider=openai` — both generate and pass
      cleanly, but note these do *not* exercise the `LiteLlm` branch in
      `deployment/config.py:resolve_model`: that branch is selected at runtime from the
      `MODEL_PROVIDER` environment variable, and the cookiecutter answer never reaches it —
      so generating a project per provider cannot exercise those branches. They're covered by
      `tests/unit/test_config.py`, the only thing that can cover them.
- [ ] `open_source_license=Proprietary` — confirm `LICENSE` is removed by
      `hooks/post_gen_project.py` and nothing else references it. Also run `Apache-2.0`: the
      shared Jinja for the license banner is easy to break with a careless strip marker, and
      indentation only shows up wrong in the rendered output.
- [ ] a non-default `python_version` (e.g. 3.12) — this is the axis most likely to expose a
      ruff/pyright rule that differs by target version.

You don't need the full cross-product — one variant per changed cookiecutter axis is
enough to catch a broken Jinja conditional.

**The gate per variant should be stricter than the defaults above** — `ruff check` +
`ruff format --check` + `pyright` + the full test suite + `pre-commit run --all-files`, plus a
check that the git tree is clean afterward — because a weaker gate is precisely what lets bugs
through. `validate-template.yml` runs four of these variants in CI on every PR, so this no
longer depends on someone remembering to do it by hand locally.

---

## 2. What to test by hand (can't be scripted, or not worth scripting yet)

### 2a. Local agent behavior (`make dev`)

```bash
cd /tmp/agent-test/test-agent
cp .env.example .env
# fill in GOOGLE_API_KEY (or your chosen provider's key) in .env
make dev   # opens http://localhost:8000, ADK web UI
```

- [ ] Send a normal message, confirm a coherent reply comes back
- [ ] Trigger `get_current_datetime` and `web_search` explicitly ("what time is it",
      "search for X") — confirm both tools actually fire and return results, not just that
      the model claims to have called them. **Note:** with no `SERPAPI_API_KEY` set,
      `web_search` returns a stub `SearchResult` unconditionally (see
      `agent/tools/example_tools.py`) — the model faithfully reporting "I can't search
      right now" in that case is *correct* behavior, not a bug; don't mistake it for a
      tool failure.
- [ ] Try one prompt-injection-style input and one PII-bearing input — confirm
      `prompts/system/safety.md` guidance actually holds in a live conversation, not just
      in the promptfoo dataset (`tests/evals/datasets/skills/safety_*.jsonl`) — the eval
      suite tests the *prompt*, this tests the *running agent* with real model sampling
      variance.
- [ ] Watch stdout while doing this — confirm `@instrument` JSON log lines appear for each
      tool call (`agent/observability.py`) and look correctly shaped (see the log-field
      table in the generated `CLAUDE.md`). This only applies to *tool-invoking* messages
      (datetime/search) — the injection/PII probes above don't call a tool, so there's
      nothing to check for PII leakage in `@instrument` log fields from those; that check
      only matters when PII flows through an instrumented tool call's arguments.

### 2b. Cross-check generated docs against generated code

Cookiecutter-templated docs drift from the code they describe more easily than normal docs
(no compiler catches a stale Jinja block). Read the generated `README.md` and `CLAUDE.md`
top to bottom against the actual generated tree and confirm:

- [ ] Every make target the docs mention exists in the generated `Makefile` and does what's
      described, and every target in the `Makefile` is documented in at least one of
      README/CLAUDE.md's tables.
- [ ] The environment variable table matches what `deployment/config.py` and
      `.env.example` actually reference.
- [ ] `AGENTS.md` / `CONTRIBUTING.md` / `SECURITY.md` render without leftover `{{ }}` /
      `{% %}` template syntax anywhere — also check `README.md`, `CLAUDE.md`,
      `CHANGELOG.md`, `LICENSE`, `pyproject.toml`.

### 2c. GitHub repo mechanics (needs a real GitHub repo, not just local files)

This is the section most likely to hide bugs that only show up against real GitHub
infrastructure — a generated project that never actually committed anything, an untracked
`uv.lock`, split CI jobs held to the wrong coverage bar, an eval job that silently never ran.
Static inspection of the template can't catch any of these; only a real push/PR can.

**`${{ ... }}` is Jinja before it is GitHub Actions.** Any workflow added under
`{{cookiecutter.project_slug}}/.github/workflows/` must wrap GitHub expressions in
`{% raw %}...{% endraw %}`, or generation fails outright with `'secrets' is undefined`.

**Trigger matrix.** On a PR to `main` in a generated project, `ci.yml` (4 jobs), `lint-pr.yml`,
`eval.yml` and `cruft-check.yml` run — **7 checks**. `deploy.yml` (push to `main` + manual
dispatch) and `security.yml` (push + weekly cron) do **not** run on PRs.

Full check names, for anyone configuring required status checks on a generated repo:

```text
Lint, format & type-check
Unit tests
Integration tests (mocked LLM)
Coverage (full suite)
Check PR title format
Prompt Security Evaluation
Template drift check (non-blocking)
```

`cruft-check.yml` crashes with `BadName: Ref '' did not resolve to an object` when
`.cruft.json`'s `commit` is empty — which is what plain `cookiecutter . --no-input` produces.
Left unhardened by decision: anyone following the documented `cruft create gh:org/repo` flow
gets a real SHA and never hits it.

---

## 3. Deploy once by hand — the real end-to-end test

This is the only way to know the Vertex AI Agent Engine path actually works; nothing above
touches GCP.

### The template is designed for many agents in one GCP project — read this first

This shapes every step below, and getting it wrong is how you break a sibling agent. Some
resources are **shared across every agent in the project**; the rest are per-agent:

| Resource | Scope | Name |
| --- | --- | --- |
| Staging bucket | **shared** | `gs://<project>-agent-staging` (uniform bucket-level access) |
| OpenTofu state bucket | **shared** | `gs://<project>-agents-state` |
| Workload Identity pool | **shared** | `github-oidc`, provider `github` (managed in `geg-core-infra`) |
| Staging subfolder | per-agent | `gs://<project>-agent-staging/<project_slug>/` |
| OpenTofu state | per-agent | `gs://<project>-agents-state/<project_slug>/<env>/` |
| Agent Engine resource | per-agent | display name = `project_slug`, created by `infra/agent/` |
| Runtime identity | per-agent | the engine's Agent Identity (`spec.effective_identity`) |
| CI principal | per-agent, per-environment | `principalSet://…/attribute.repository_environment/<org>/<repo>:<env>` |
| Dashboard | per-agent | `"<project_name> — Agent Engine"` |
| Alert policies | per-agent | `"<project_name> — high error rate"` / `"— high p95 latency"` |

`config.py` states the intent directly — `gcs_dir_name=_project_name()`, commented "so
artifacts land at `<bucket>/<project_slug>/` instead of the generic default". And
`setup_gcp.sh`'s "already exists, skipping" is not a fallback: it is how the second and every
later agent deliberately adopts the shared buckets.

**So a shared team project is a valid target.** A new agent joins alongside earlier ones
rather than colliding. What is *not* safe is deleting the shared pieces during teardown — see
the Teardown section, which is the one place this model genuinely changes what you run.

Consequences worth knowing:

- **Each agent has its own identity.** `infra/agent/main.tf` grants it `cloudtrace.agent`
  and `logging.logWriter`; model calls come from the Google-managed `agentDefaultAccess`
  grant on the project. Revoking one agent's access does not touch its siblings, and Cloud
  Logging attributes activity to the agent that did it.
- **CI is scoped to one agent and one environment too.** `infra/agent/ci.tf` lets the
  repository, in one GitHub environment, update only its own engine, read only its own state
  prefix and write only its own `<project_slug>/` folder of the staging bucket. The SDK
  uploads under `gcs_dir_name`, never to the bucket root, so the folder condition costs
  nothing. Reading the bucket's metadata and `serviceUsageConsumer` stay project-wide.
- **`make setup-monitoring` may attach alert policies to an existing notification channel.**
  The display names are per-agent so they will not overwrite a sibling's, but if anyone is
  on-call for the project, check the channels first or skip that step.

### CI deploys without a key

`deploy.yml` signs in through Workload Identity Federation: GitHub's OIDC token is exchanged
in the project's pool, and the APIs see the repository itself as the caller. Nothing is
stored as a secret. What has to exist first:

- the pool `github-oidc` and its `github` provider, mapping `attribute.repository_environment`
  (shared, once per project, managed in `geg-core-infra`; `setup_gcp.sh` prints the provider
  name)
- `make infra-apply` run for the environment, with `GITHUB_REPOSITORY=<org>/<repo>` (derived
  from the `origin` remote), so `ci.tf` creates the repository's grants for it
- the repository variables `GCP_WORKLOAD_IDENTITY_PROVIDER` and `GOOGLE_CLOUD_PROJECT`

A job holds those grants only if it names the environment (`environment: dev|prod`), and
GitHub issues that claim only after the environment's protection rules have passed. A
workflow on a feature branch that names none gets nothing.

CI never runs `tofu apply`. It reads the engine name from the state and ships code to it.

### Generate a fresh project

Generate via `cruft` — the documented flow — so `.cruft.json` is realistic:

```bash
export ADK_TEST_PROJECT=example-gcp-project # or a fresh throwaway project
mkdir -p /tmp/agent-deploy && cd /tmp/agent-deploy
uv --directory /path/to/agent-deployment-template run \
  cruft create https://github.com/philippschaedle/agent-deployment-template \
  --no-input -y --extra-context "{\"project_name\":\"Deploy Test Agent\",\"gcp_project_id\":\"$ADK_TEST_PROJECT\"}"
# uv --directory sets the cwd, so the project lands in the template repo:
mv /path/to/agent-deployment-template/deploy-test-agent /tmp/agent-deploy/
cd /tmp/agent-deploy/deploy-test-agent
git status --short   # expect empty — also confirms the cruft dirty-tree fix

cp .env.example .env
# GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION are pre-filled from the answers above.
# Add: GCS_STAGING_BUCKET=gs://<project>-agent-staging
# GOOGLE_API_KEY is NOT needed — the deployed agent runs on Vertex under its Agent Identity.
```

Confirm the target before spending anything:

```bash
gcloud projects describe "$ADK_TEST_PROJECT" --format='value(projectId,lifecycleState)'
gcloud billing projects describe "$ADK_TEST_PROJECT" --format='value(billingEnabled)'
```

### Bootstrap

```bash
make setup-gcp ENV=dev
```

- [ ] Expect **"already exists, skipping"** for the staging and state buckets when targeting
      a project that already hosts an agent. That is correct, not a warning.
- [ ] Confirm no service account is created and no key is written.
- [ ] Confirm `setup-gcp` is idempotent — run it twice against a project that already has
      these resources and confirm no duplicates or errors. Separately, verify the *fresh-create*
      path against a genuinely empty project — this is easy to skip if every project you test
      against already hosts an agent.

### Deploy

```bash
make deploy-dev
```

- [ ] Watch it: `tofu apply` creates the engine and its grants and prints `agent_principal`
      → `deploy.py` pickles `root_agent` and updates that engine, logging `Python: 3.1x`
      → `health_check.py` retries the smoke test while the new grants propagate
- [ ] Confirm the build log in Cloud Build shows this project's Python version, not 3.10
- [ ] Run `make deploy-dev` a second time and confirm OpenTofu plans no changes and the same
      engine is updated, not a second one created
- [ ] Confirm the artifacts landed under this agent's own subfolder,
      `gs://$ADK_TEST_PROJECT-agent-staging/deploy-test-agent/`, and left any sibling's
      subfolder untouched

```bash
export AGENT_ENGINE_RESOURCE_NAME="$(tofu -chdir=infra/agent output -raw agent_resource_name)"
make health-check      # standalone, no fresh deploy; expect exit 0
make logs
make traces
```

- [ ] Confirm `make logs` actually surfaces the smoke test's `@instrument` JSON lines and
      that `make traces`'s printed filter matches real spans — not merely that the commands
      exit 0. Note a shared project makes this easier to misread: filter by this agent's
      resource name or `jsonPayload.agent_name`, or a sibling agent's traffic will look like
      yours.

If `make logs` / `make traces` come back empty against a resource you know just took traffic,
compare directly against the metrics resource type:

```bash
gcloud logging read 'resource.type="aiplatform.googleapis.com/ReasoningEngine"' \
  --project="$ADK_TEST_PROJECT" --limit=5
```

- [ ] `make setup-monitoring` twice — confirm the dashboard and both alert policies appear
      under the project, that their names carry **this** agent's `project_name`, and that a
      second run updates rather than duplicates. Check the notification-channel caveat above
      first.
- [ ] Test rollback: make a trivial change (e.g. edit `prompts/tasks/example_task.md`),
      commit it, `make deploy-dev` again so a second version exists, then:

  ```bash
  make rollback REF=<first commit's short sha> ENV=dev
  make health-check
  ```

  Confirm it checks out the ref, redeploys, and restores your original branch afterwards —
  including after a deliberately-broken intermediate commit, to prove the branch restore
  happens on failure too — and that `health-check` passes against the rolled-back version.

### Teardown — per-agent only

**The shared staging bucket, state bucket and Workload Identity pool must survive.** Deleting
any of them breaks every other agent in the project. Deleting a shared resource during
teardown is a documented past mistake — don't repeat it.

```bash
# 1. this agent's engine (the billable one) and every grant to its identity and its CI.
make infra-init ENV=dev
make -n infra-apply ENV=dev          # prints the -var flags
tofu -chdir=infra/agent destroy <those -var flags>

# 2. only this agent's staging subfolder
gsutil -m rm -r "gs://$ADK_TEST_PROJECT-agent-staging/deploy-test-agent/"

# 3. this agent's dashboard and two alert policies, by display name (Console or gcloud)
```

- [ ] Do **not** delete the state bucket or the Workload Identity pool
- [ ] Do **not** run `gsutil rm -r` against the bucket root
- [ ] Confirm any sibling agent's subfolder is still present afterwards
- [ ] Don't leave a `.env` with real values behind in `/tmp/agent-deploy`

If instead you used a genuinely throwaway project, `gcloud projects delete <project>` removes
everything in one step and is the safer teardown — nothing shared, nothing to preserve.

## 4. Transferring an existing agent into this template

This is a migration, not a fresh build — the goal is zero behavior change, just a new
shell around the existing agent. Do this in a **separate branch of the new generated repo**,
not inside this template repo.

1. **Generate the new repo first, empty**, exactly as in §1c, and get `make dev` working
   with the stock example tool before touching anything — confirms the scaffold itself is
   sound before you start pouring in existing code.
2. **Inventory the source agent** before moving anything:
   - [ ] What ADK constructs does it use — plain `Agent()`, `sub_agents=[...]`, custom
         tool wrappers, custom callbacks? This template assumes "no custom classes, no
         inheritance — pure ADK syntax only" (per generated `CLAUDE.md`); flag anywhere the
         existing agent deviates, since that's extra migration work, not a drop-in.
   - [ ] Which model provider does it currently use, and does it match one of
         `google` / `anthropic` / `openai` / `litellm` in `deployment/config.py`?
   - [ ] Are prompts already externalized to files, or inline strings that need
         extracting into `prompts/system/` and `prompts/tasks/` plus a `prompts.yaml`
         registry entry?
3. **Port tools** into `agent/tools/`: one file per logical group, each function
   type-annotated and docstring'd (ADK builds the tool schema from these), wrapped in
   `@instrument`, re-exported from `agent/tools/__init__.py`, and wired into
   `tools=[...]` in `agent/agent.py`. Write/port unit tests into `tests/unit/test_tools.py`
   for each as you go — don't batch this at the end.
4. **Port prompts** into `prompts/system/*.md` and `prompts/tasks/*.md`, register each in
   `prompts/prompts.yaml`. Diff the *effective* concatenated prompt (`load_prompt()`
   output) against the original agent's system prompt string — a line dropped during copy
   is a silent behavior change, not an error.
5. **Port or write eval cases**: add the existing agent's known-good and known-bad
   examples into `tests/evals/datasets/skills/*.jsonl` (or a new file, registered in
   `promptfoo.yaml`). If the source agent has no eval suite today, this is the point where
   it gets one — don't skip it just because it's new work.
6. **Re-run the full gate**: §1c's `make lint && make typecheck && make test && make eval`
   locally, then §2a's manual `make dev` conversation check, focused specifically on the
   behaviors the old agent was known for (its trickiest tool call, its safety edge cases).
7. **Deploy once by hand** per §3, against a genuinely separate dev GCP project/resource —
   not the old agent's production Agent Engine resource — and compare its `make eval`
   pass rate and a handful of manual conversations side-by-side against the old
   deployment before ever pointing real traffic at the new one.
8. Only after 6 and 7 both pass: retire the old deployment, on a timeline your team is
   comfortable with (keep it live in parallel for a while rather than a hard cutover).
