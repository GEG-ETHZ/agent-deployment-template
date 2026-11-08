# AGENTS.md — {{cookiecutter.project_name}}

Single source of truth for working on this repository — for people and for AI
assistants alike. `CLAUDE.md` points here and holds no content of its own.

## Part A — using this

### What this project is

**{{cookiecutter.project_name}}** is a Google ADK agent deployed on Vertex AI Agent Engine. It is built from the [agent-deployment-template](https://github.com/{{cookiecutter.github_org}}/agent-deployment-template) cookiecutter.

### Setup (run this once, in order)

Prerequisites: Python {{cookiecutter.python_version}}+, `uv`, Node.js 22+ (promptfoo requires it), `gcloud` CLI

```bash
# 1. Install dependencies
make install

# 2. Configure environment
cp .env.example .env
# Edit .env — fill in at minimum: GOOGLE_CLOUD_PROJECT.
# For the model, pick one:
#   - GOOGLE_GENAI_USE_VERTEXAI=TRUE (the default in .env.example) and run
#     `gcloud auth application-default login` — no API key needed
#   - or unset it and supply GOOGLE_API_KEY from AI Studio

# 3. Install pre-commit hooks
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg

# 4. Run the agent locally
make dev   # opens http://localhost:8000
```

For GCP deployment (one-time):

```bash
# Deploying locally needs BOTH credential stores. `gcloud auth login` does not
# refresh Application Default Credentials, and `vertexai.init()` reads ADC — so
# logging in only to the CLI fails partway through a deploy with a RefreshError.
gcloud auth login
gcloud auth application-default login

make setup-gcp ENV=dev   # enables APIs, creates the staging and OpenTofu state buckets
make deploy-dev          # OpenTofu: engine, identity, roles; then ship the code; health-check
```

Deploying also needs [OpenTofu](https://opentofu.org) (`tofu` ≥ 1.8) on your path, and an
account that may change project IAM (`roles/resourcemanager.projectIamAdmin` or owner), because
OpenTofu grants the agent's identity its roles.

### Make targets (use these, not raw commands)

| Target | What it does |
|---|---|
| `make dev` | Run agent locally at http://localhost:8000 |
| `make test` | Unit tests with coverage |
| `make test-unit` | Unit tests only, verbose |
| `make test-integration` | Integration tests only |
| `make eval` | promptfoo red-team evaluation |
| `make lint` | ruff lint check |
| `make format` | ruff format |
| `make typecheck` | pyright |
| `make pre-commit` | All pre-commit hooks |
| `make deploy-dev` | Apply `infra/agent/` (engine, Agent Identity, roles), ship the code to that engine, health-check it |
| `make deploy-prod` | Same, for prod |
| `make infra-apply ENV=dev\|prod` | Create or update the engine and its grants only (OpenTofu, `infra/agent/`) |
| `make infra-import ENV=dev\|prod ENGINE=<name>` | One-time: bring an engine created outside OpenTofu under its state |
| `make deploy-code ENV=dev\|prod` | Ship the code to the existing engine and health-check it, without applying — what `deploy.yml` runs |
| `make infra-test` | OpenTofu fmt, validate and tests — offline, mocked provider |
| `make rollback REF=<tag> [ENV=prod\|dev]` | Redeploy a previous git ref against the existing Agent Engine resource |
| `make health-check` | Standalone smoke test against the deployed Agent Engine resource (no fresh deploy) |
| `make logs` | Read this agent's Cloud Logging entries |
| `make traces` | List this agent's Cloud Trace spans |
| `make setup-gcp` | One-time GCP bootstrap |
| `make setup-monitoring` | One-time Cloud Monitoring dashboard + alert policy bootstrap |
| `make clean` | Remove caches, coverage output and build artefacts |
| `make help` | List every target with its description |

### Multi-provider model selection

Set `MODEL_PROVIDER` in `.env`:

| Value | Model | Requires |
|---|---|---|
| `google` (default) | Gemini 2.5 Pro | `GOOGLE_API_KEY` (local) or ADC (GCP) |
| `anthropic` | Claude Opus 4.8 via LiteLLM | `ANTHROPIC_API_KEY` |
| `openai` | GPT-4o via LiteLLM | `OPENAI_API_KEY` |
| `litellm` | Set `LITELLM_MODEL` | depends on model |

> **Only `google` works once deployed.** `deploy.py` does not forward `ANTHROPIC_API_KEY` or
> `OPENAI_API_KEY` to the Agent Engine container, so `anthropic`, `openai` and any `litellm` model
> that needs an API key deploy fine and then fail on every request. They work locally, where the
> key comes from `.env`.

### Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | Deploy only | — | GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | Deploy only | `europe-west1` | Vertex AI region |
| `GCS_STAGING_BUCKET` | No | `gs://$GOOGLE_CLOUD_PROJECT-agent-staging` | Override only if you renamed the bucket; the `gs://` scheme is optional |
| `AGENT_ENGINE_RESOURCE_NAME` | Standalone `health-check` / `deploy.py` only | — | Engine to query or update. `make deploy-*` and `make rollback` set it from the OpenTofu output, so it does not belong in `.env` |
| `STATE_BUCKET` | No | `$GOOGLE_CLOUD_PROJECT-agents-state` | OpenTofu state bucket shared by every agent of the project |
| `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY` | No | — | `deploy.py` sets `true` on the deployed agent: Agent Engine's built-in tracing |
| `CLOUD_TRACE_ENABLED` | No | off | Our own span exporter, for local runs only — it fails under Agent Identity (see Observability) |
| `OTEL_EXPORTER_GCP_TRACE_PROJECT_ID` | With `CLOUD_TRACE_ENABLED` | — | Project our span exporter writes to |
| `MODEL_PROVIDER` | No | `google` | Provider selection |
| `LITELLM_MODEL` | If provider=litellm | — | Full LiteLLM model string |
| `ANTHROPIC_API_KEY` | If provider=anthropic | — | |
| `OPENAI_API_KEY` | If provider=openai | — | |
| `GOOGLE_GENAI_USE_VERTEXAI` | Local dev on ADC | — | `TRUE` routes Gemini through Vertex AI and ADC. Without it google-genai uses the AI Studio backend and demands `GOOGLE_API_KEY`, even when ADC is valid |
| `GOOGLE_API_KEY` | Local dev | — | Only when `GOOGLE_GENAI_USE_VERTEXAI` is unset or `FALSE`. Not needed on GCP (uses ADC) |
| `SERPAPI_API_KEY` | No | — | Enables live web search; omit for stub |

### Health check

`deployment/scripts/health_check.py` creates a session on the Agent Engine resource named by
`AGENT_ENGINE_RESOURCE_NAME`, sends a message to it in a second request, and requires at least
one event back, following the same two-request path as the console playground and real clients.
It tries up to six times, 20 seconds apart (`--attempts` changes the count), because new role
grants take a minute or two to take effect. `make deploy-*` runs it last, once the code is live;
`deploy.py` itself does not query the agent. It also runs standalone against an already-deployed
resource:

```bash
AGENT_ENGINE_RESOURCE_NAME="$(tofu -chdir=infra/agent output -raw agent_resource_name)" \
  make health-check                                                  # after make infra-init ENV=<env>
uv run python deployment/scripts/health_check.py --message "hello"   # customize the ping
```

Exits `0` on success, `1` on failure, so it's safe to gate CI or a cron job on. `deploy.yml` runs
it as its own step right after deploying, reading the resource name from `.agent_engine_resource`,
which `deploy.py` writes.

### Rollback

Agent Engine deploys are **source-based** (`agent_engines.update` pickles `root_agent` directly)
— there is no container image digest to pin a rollback to. Rolling back means checking out a
previous git ref and redeploying its code to the *existing* engine from the OpenTofu state, which
`deploy.py` updates in place.

**Locally:**

```bash
make rollback REF=v1.2.0                # redeploys v1.2.0 to prod
make rollback REF=v1.2.0 ENV=dev        # redeploys v1.2.0 to dev
```

This reads the engine name from the `<ENV>` OpenTofu state, checks out `REF`, runs
`deployment/deploy.py --env <ENV>` against that engine, restores your original branch afterwards
regardless of whether the deploy succeeds, and then runs the health check. It does not apply
OpenTofu: the engine, its identity and its grants stay as they are.

**Via GitHub Actions:** manually trigger the `deploy.yml` workflow (Actions tab → Deploy → Run
workflow) and set the `ref` input to the tag, branch, or SHA you want to roll back to, alongside
the `environment` input. Leaving `ref` empty deploys the triggering ref as usual.

After either path, run `make health-check` to confirm the resource is responding — useful when
you want to verify a rollback worked without triggering another deploy.

### Runtime identity

Two identities are involved in a deploy:

| Identity | What it is |
|---|---|
| The **deployer** | Whoever runs `make deploy-*`: your own account, through Application Default Credentials |
| The **runtime** | Whoever the deployed agent runs *as* when it serves a request: its own **Agent Identity** |

`infra/agent/` (OpenTofu) creates the engine with `spec.identity_type = "AGENT_IDENTITY"` and no
code. That is enough for Vertex AI to give that one agent its own IAM principal, derived from its
resource name:

```text
principal://agents.global.org-<ORG_ID>.system.id.goog/resources/aiplatform/projects/<PROJECT_NUMBER>/locations/<LOCATION>/reasoningEngines/<ENGINE_ID>
```

The API reports the same value, without the scheme, as the resource's `spec.effectiveIdentity`;
OpenTofu reads it from there and grants roles to it, so the principal is never assembled by hand.
Without `identity_type`, the agent would run as the project's shared Reasoning Engine Service
Agent, which every agent in the project shares. `deploy.py` sends the same `identity_type` with
every code update, so a deploy cannot move the agent off its identity either.

**Where the identity's permissions come from:**

| Grant | Who sets it | Covers |
|---|---|---|
| `roles/aiplatform.agentDefaultAccess` (ALPHA) on `principalSet://agents.global.org-<ORG_ID>.system.id.goog/attribute.platformContainer/aiplatform/projects/<PROJECT_NUMBER>` | Google, automatically, when the first agent with Agent Identity is created in the project | Every Agent Engine agent in the project: model calls (`aiplatform.endpoints.predict`), traces, log entries, metrics |
| `roles/cloudtrace.agent` on this agent's principal | `infra/agent/` | Export spans (`agent/observability.py`) |
| `roles/logging.logWriter` on this agent's principal | `infra/agent/` | Write log entries |

The default binding is in no repository, and anyone with project IAM rights, or an
OpenTofu/Terraform run that owns the project policy, can remove it. Traces and logs are granted
here as well so they survive that. **Model calls rely on the default binding alone**:
`roles/aiplatform.user` is not granted, because it can also create and delete Vertex resources.
If the agent starts failing with `PermissionDenied` on `aiplatform.endpoints.predict`, check
the binding still exists:

```bash
gcloud projects get-iam-policy $GOOGLE_CLOUD_PROJECT --project=$GOOGLE_CLOUD_PROJECT \
  --flatten='bindings[].members' --filter='bindings.role=roles/aiplatform.agentDefaultAccess' \
  --format='value(bindings.members)'
```

#### Adding permissions for this agent

A tool that needs more (a BigQuery dataset, a bucket, a secret) gets it from a file of this
project's own in `infra/agent/`, for example `infra/agent/data_access.tf`. Do not edit
`main.tf`, `ci.tf` or the `roles` default in `variables.tf`: the template owns those files, so
every `cruft update` would conflict with the edit. A file the template never ships is left alone
by every update, and OpenTofu reads every `.tf` file in the directory, so it applies with the
rest on the next `make infra-apply`.

Grant to the two principals the module already defines, and scope each grant to the resource
rather than the project where the resource type allows it:

| Local | Who it is | Use it for |
|---|---|---|
| `local.agent_principal` | The deployed agent at runtime (its Agent Identity) | Data and secrets the tools read when serving a request |
| `local.ci_principal` | The GitHub repository, signed in through Workload Identity Federation | Anything `deploy.yml` itself has to reach; `null` when `github_repository` is empty |

```hcl
# infra/agent/data_access.tf -- project-owned; the template does not ship this file.

locals {
  dvc_buckets = ["my-dvc-remote-bucket"]
}

resource "google_storage_bucket_iam_member" "data" {
  for_each = toset(local.dvc_buckets)
  bucket   = each.value
  role     = "roles/storage.objectViewer"
  member   = local.agent_principal
}

resource "google_bigquery_dataset_iam_member" "data" {
  project    = var.project_id
  dataset_id = "my_dataset"
  role       = "roles/bigquery.dataViewer"
  member     = local.agent_principal
}

# Running queries is a project-level permission: there is no per-dataset jobUser.
resource "google_project_iam_member" "bigquery_jobs" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = local.agent_principal
}

resource "google_secret_manager_secret_iam_member" "git_token" {
  project   = var.project_id
  secret_id = "git_auth_token"
  role      = "roles/secretmanager.secretAccessor"
  member    = local.agent_principal
}

# Only if CI needs more than ci.tf grants; count keeps it off without a repository.
resource "google_storage_bucket_iam_member" "ci_artifacts" {
  count  = local.ci_enabled ? 1 : 0
  bucket = "my-ci-artifact-bucket"
  role   = "roles/storage.objectViewer"
  member = local.ci_principal
}
```

- **Use `_iam_member`, never `_iam_binding` or `_iam_policy`.** Those are authoritative: they
  remove every other member of the role, or every other grant on the resource, including the
  grants of sibling agents and of people.
- **Resources in another project** take that project's id in `project`; the person running
  `make infra-apply` then needs IAM rights there too.
- **The grants follow the engine.** Re-creating it (a new `region`, a `tofu destroy`) changes
  `local.agent_principal`; the next apply grants the new principal and removes the old one's
  grants, so nothing is left behind on a principal that no longer exists.
- **Test it in a file of its own**, for example `infra/agent/tests/data_access.tftest.hcl`:
  `agent.tftest.hcl` is a template file too. Copy its `mock_provider` blocks, which every test
  file needs, and assert each grant's member and role, so `make infra-test` catches a grant that
  went to the wrong principal.

The order is fixed, and `make deploy-*` runs it:

1. `make infra-apply` creates the engine on first run (and with it the identity), and grants the
   roles. Later applies change nothing unless the module changed.
2. `deploy.py` ships the code to the engine named by the OpenTofu output. It never creates one: a
   created engine would be a second agent, outside the state and without these grants.
3. The health check runs last.

OpenTofu owns the engine and its identity; `deploy.py` owns its code. The engine's
`lifecycle.ignore_changes` lists the code fields (`package_spec`, `deployment_spec`,
`agent_framework`, `class_methods`), so an apply never undoes a deploy. Anything that forces a
new engine — a different `region`, or destroying it — creates a new principal: the next apply
grants the new one and removes the old one's grants.

An engine created before this module existed is adopted once, so it keeps its ID and identity:

```bash
make infra-import ENV=dev ENGINE=projects/<number>/locations/<region>/reasoningEngines/<id>
```

State lives in `gs://$GOOGLE_CLOUD_PROJECT-agents-state`, shared by every agent of the project
under one prefix per agent and environment (`{{cookiecutter.project_slug}}/dev`, `{{cookiecutter.project_slug}}/prod`). Each prefix is
its own state file with its own lock.

No service account is involved, so the deployer needs no `iam.serviceAccountUser` (`actAs`).

To check what a deployed resource runs as, read `spec.identityType` and `spec.effectiveIdentity`:

```bash
curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://$GOOGLE_CLOUD_LOCATION-aiplatform.googleapis.com/v1/$(tofu -chdir=infra/agent output -raw agent_resource_name)" \
  | jq '.spec | {identityType, effectiveIdentity}'
```

> **Upgrading an existing project — breaking.** A project generated before this change runs its
> agent as `agent-engine-sa`, on an engine `deploy.py` created. After a `cruft update`:
>
> 1. `make setup-gcp ENV=<env>` creates the OpenTofu state bucket.
> 2. Move every permission the agent got through `agent-engine-sa` beyond model, trace and log
>    access (datasets, buckets, secrets) into a file of your own; see "Adding permissions for
>    this agent" above. The new identity inherits nothing.
> 3. `make deploy-<env>` creates a new engine with its own Agent Identity, grants its roles and
>    ships the code. Then remove `AGENT_ENGINE_RESOURCE_NAME` from `.env`, point API consumers
>    at the new engine and delete the old one by hand.
>
> Adopting the old engine with `make infra-import` instead, to keep its ID, is untested: whether
> an existing engine can switch from a service account to Agent Identity in place is not
> confirmed. `agent-engine-sa` itself is left in place: other deployments may still use it.

### Monitoring & alerting

Vertex AI Agent Engine emits platform-level metrics automatically under the
`aiplatform.googleapis.com/ReasoningEngine` monitored resource — no instrumentation needed for
these (unlike the app-level structured logging in `agent/observability.py`):

| Metric | Description |
|---|---|
| `reasoning_engine/request_count` | Request count, labeled by `response_code` / `response_code_class` |
| `reasoning_engine/request_latencies` | Request latency distribution (ms) |
| `reasoning_engine/cpu/allocation_time` | Container CPU allocation time |
| `reasoning_engine/memory/allocation_time` | Container memory allocation time |

`deployment/monitoring/` builds a dashboard and two alert policies on top of these, applied via
plain `gcloud` (consistent with `setup_gcp.sh`; OpenTofu manages only the agent identity's grants):

- `dashboard.json` — request count by response code, p50/p95/p99 latency, CPU/memory allocation
- `alerting/error_rate.json` — 5xx response rate > 5% over 5 minutes (ratio condition via
  `denominatorFilter`, matching total request count)
- `alerting/latency_p95.json` — p95 request latency > 3000ms over 5 minutes

```bash
make setup-monitoring                                    # dashboard + alerts, no notifications
ALERT_EMAIL=oncall@example.com make setup-monitoring      # + email notification channel
SLACK_CHANNEL="#agent-alerts" SLACK_BOT_TOKEN=xoxb-... \
  make setup-monitoring                                   # + Slack notification channel
```

Safe to re-run: it updates the existing dashboard/policies/channels by display name instead of
creating duplicates. Editing `dashboard.json` and re-running is the intended way to change the
dashboard. (The Dashboards API rejects an update without the dashboard's current `etag`, which a
checked-in config file cannot carry, so `setup_monitoring.sh` reads the live `etag` and injects it
before updating.) Run once per GCP project (dev and prod separately, same as `setup-gcp`).
Preview a dashboard change first with `gcloud monitoring dashboards create --config-from-file=
deployment/monitoring/dashboard.json --validate-only --project=$GOOGLE_CLOUD_PROJECT`.

**Not covered here:** rate-limit/quota alerting. Vertex AI doesn't expose a per-agent quota metric
to threshold on — configure that separately via Cloud Console → IAM & Admin → Quotas → Create
Alert.

### CI/CD overview

| Workflow | Trigger | What it checks |
|---|---|---|
| `ci.yml` | push + PR | lint, format, typecheck, OpenTofu fmt/validate/tests, unit tests, combined-suite coverage |
| `lint-pr.yml` | PR opened/edited | PR title is a valid conventional commit |
| `security.yml` | push to main + weekly | CodeQL, pip-audit CVEs, secret scan |
| `eval.yml` | PR to main | promptfoo red-team (90% pass threshold) |
| `deploy.yml` | `ci.yml` passing on main | logs in through Workload Identity Federation, then `make deploy-code ENV=prod`: reads the engine from the OpenTofu state, ships that commit's code, health-checks. It never applies |
| `cruft-check.yml` | push + PR + weekly | non-blocking: warns if `cruft update` is available from the template |

### Required GitHub Environments

`deploy.yml`'s job targets a GitHub Environment named `dev` or `prod` (Settings → Environments →
New environment), matching its `environment` `workflow_dispatch` input — a push to `main` deploys
to `prod` once `ci.yml` has passed on it, and never when it fails. Each environment should point
at its own GCP project, so dev and prod need their own **Environment variables** — not repository-level ones,
which would make both environments deploy to the same place. None of them is a secret: there is no key.

| Name | Kind | Scope | Description |
|---|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | Variable | Per environment | That environment's GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | Variable | Per environment | Vertex AI region |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Variable | Per environment | `projects/<number>/locations/global/workloadIdentityPools/github-oidc/providers/github` |
| `MODEL_PROVIDER` | Variable | Per environment | `google` \| `anthropic` \| `openai` \| `litellm` |
| `GCS_STAGING_BUCKET` | Variable | Per environment | Optional — derived from the project id unless you renamed the bucket |
| `GOOGLE_API_KEY` | Secret | Repository-level | Used only by `eval.yml` (promptfoo), not per-environment  <!-- pragma: allowlist secret --> |

The engine name is not configured anywhere: `make deploy-code` reads it from the environment's
OpenTofu state, as a local deploy does.

**How CI gets into GCP.** `google-github-actions/auth` exchanges the run's GitHub OIDC token in
the existing pool `github-oidc` (provider `github`, which accepts only this organisation's
repositories). There is no service account: the APIs see this repository in one environment,
`principalSet://…/attribute.repository_environment/<owner>/<repo>:<env>`. `infra/agent/ci.tf`
grants it, and only it, what a code deploy needs:

| Grant | Scope | Why |
|---|---|---|
| `roles/aiplatform.user` | this agent's engine only | update its code, query it in the health check |
| `roles/storage.objectAdmin` | the shared staging bucket, objects under `<agent>/` only | upload the pickle and its files. CI cannot write, overwrite or list other agents' folders: a pickle it replaced there would run under that agent's identity |
| `roles/storage.bucketViewer` | the shared staging bucket | the SDK reads the bucket's metadata (`storage.buckets.get`) before uploading |
| `roles/storage.objectViewer` | the state bucket, objects under `<agent>/` (plus listing) | read the engine name |
| `roles/serviceusage.serviceUsageConsumer` | the project | bill its API calls to the project; no data access |

The repository comes from `GITHUB_REPOSITORY` (set by GitHub) or the `origin` remote, and the grants
are made by a local `make infra-apply`. CI never applies, so it holds no IAM rights. The pool
and provider are owned by the `geg-core-infra` repository (module `github-oidc-pool`) and only
referenced here.

**The environment is part of the grant, so the GitHub rules on it apply.** Only a job that
declares `environment: <env>` receives a token for that environment, and GitHub issues it only
after the environment's protection rules have passed. A workflow on a feature branch that names
no environment, or the other one, gets nothing. Without that, a grant on the repository alone
would let any branch's workflow deploy to `prod` and skip its reviewers. So protect `prod` on
the GitHub side: a required reviewer and a deployment-branch rule limited to `main`. `dev` may
stay open.

Bootstrap each environment's GCP project with `make setup-gcp ENV=dev` / `make setup-gcp
ENV=prod` (see [setup_gcp.sh](deployment/scripts/setup_gcp.sh)) — it prints which variables to
add to which environment. Then `make infra-apply ENV=<env>` from a clone whose `origin` is the
GitHub repository grants CI its access.

### Claude Code slash commands

| Command | What it does |
|---|---|
| `/deploy` | Runs `make deploy-prod` and reports the resource name |
| `/eval` | Runs `make eval` and summarises results |
| `/logs` | Runs `make logs` and streams Cloud Logging output |

## Part B — changing the code

### Project layout

```text
agent/
  __init__.py          load_prompt() — reads prompts/prompts.yaml and concatenates .md files
  agent.py             root_agent definition (ADK syntax; this is the entrypoint)
  observability.py     log_event(), @instrument, redact_pii() — see Observability below
  tools/
    __init__.py        re-exports all tools
    example_tools.py   get_current_datetime, web_search (both @instrument-wrapped)
    response_models.py Pydantic schemas for tool return types
prompts/
  prompts.yaml         registry: which .md files load into which agents
  system/
    base.md            always-on identity and style instructions
    safety.md          refusal and safety guidelines
  tasks/
    example_task.md    task-specific instructions (replace with your use case)
deployment/
  config.py            resolve_model() + DeploymentConfig dataclass
  deploy.py            CLI: ship the code to the engine infra/agent created (update only)
  python_version.py    sends the local Python version with that update
  scripts/
    setup_gcp.sh       one-time GCP bootstrap
    health_check.py    smoke test against the deployed agent, with retries
    read_logs.sh       read this agent's Cloud Logging entries
    read_traces.py     list this agent's Cloud Trace spans
infra/
  agent/               OpenTofu: the agent's engine, its Agent Identity and its project roles
    tests/             `tofu test` cases, offline with a mocked provider
tests/
  unit/                pure function tests — no GCP, no network
  evals/
    promptfoo.yaml     red-team + quality eval config
    provider.py        promptfoo Python provider (runs agent inline)
    datasets/
      golden_set.jsonl reference test cases
```

### How to add a tool

1. Write the function in `agent/tools/example_tools.py` (or create a new file in `agent/tools/`)
2. Add type annotations and a docstring — ADK uses these to build the tool schema
3. Export from `agent/tools/__init__.py`
4. Add to `tools=[...]` in `agent/agent.py`
5. Add unit tests in `tests/unit/test_tools.py`

```python
# Example tool signature
def my_tool(param: str) -> str:
    """One-line description used by the model to decide when to call this tool.

    Args:
        param: Description of the parameter.

    Returns:
        Description of the return value.
    """
    ...
```

Wrap new tools with `@instrument` from `agent/observability.py` (see Observability below) the same
way `get_current_datetime` and `web_search` are — `functools.wraps` keeps ADK's tool-schema
introspection working unchanged, verified by comparing `FunctionTool` declarations before/after.

### Observability

`agent/observability.py` provides structured JSON logging, applied at the boundary this project
actually controls — tool calls — rather than `Runner.run_async`, which Agent Engine's managed
runtime drives internally and which our code never touches in production:

- **`@instrument`** — wraps a tool function (sync or async) and logs `<name>.start`,
  `<name>.end` (with `duration_ms`), or `<name>.error` (with the exception message) as JSON.
  Already applied to both tools in `agent/tools/example_tools.py`.
- **`log_event(event_type, fields, severity="INFO")`** — emit one structured JSON line for
  anything else worth recording. `CloudLoggingHandler` parses that JSON line into a
  `jsonPayload`, and the Python log level (chosen from `severity`) sets the LogEntry's own
  severity field, so `severity=ERROR` is filterable directly in Logs Explorer.
- **`redact_pii(value)`** — recursively redacts emails, SSNs, and credit-card-shaped numbers from
  strings, dicts, and lists. `log_event` and `@instrument` both redact fields before logging them,
  but it's a defence-in-depth measure, not a substitute for not logging sensitive fields in the
  first place.
- **`log_model_usage(event)`** — logs token counts from an ADK event's `usage_metadata`, for code
  that iterates the event stream itself (the promptfoo eval provider does); not reachable from
  Agent Engine's own request path for the same reason `@instrument` doesn't wrap `Runner.run_async`.

#### Destinations

**Logs need no configuration.** Agent Engine forwards container stdout/stderr to Cloud Logging
under `aiplatform.googleapis.com/reasoning_engine_stdout` and `..._stderr`, and parses a JSON
stdout line into a structured `jsonPayload`. `make logs` reads exactly those, scoped to this
agent by `reasoning_engine_id` — the log names are shared by every reasoning engine in the
project.

**Traces of the deployed agent come from Agent Engine's built-in telemetry.**
`deployment/deploy.py` sets one variable on the deployed resource:

| Variable | Effect |
|---|---|
| `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY` | `true`: the platform traces each request — model calls and tool calls under ADK's root span — into Cloud Trace. `make traces` lists roots only; use `read_traces.py --spans` to expand them. Without it the SDK sends `unspecified`, which an engine OpenTofu created resolves to disabled |

Prompt and response text is **not** captured: `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`
stays unset. Setting it would put user input and model output into the traces, unredacted.

**Our own exporter stays off when deployed.** `agent/observability.py` can export a span per
`@instrument`ed call itself (`CLOUD_TRACE_ENABLED`, with `OTEL_EXPORTER_GCP_TRACE_PROJECT_ID`).
Under Agent Identity that fails: the agent's access token is bound to its X.509 certificate and
is accepted only over mutual TLS, which the Cloud Trace client does not use, so every export is
rejected with `401 UNAUTHENTICATED`. Locally, with your own credentials, it still works: export
`CLOUD_TRACE_ENABLED=true` and `OTEL_EXPORTER_GCP_TRACE_PROJECT_ID=<project>` to opt in.
Telemetry never breaks a tool call: a missing library or failing export is reported on stderr
and the tool runs on.

> **If application logs seem to be missing, check the project's log sink first.**
> A disabled `_Default` sink discards every non-audit entry however it was written — including
> direct `gcloud logging write` calls — so it looks exactly like broken instrumentation. This
> cost a full debugging session: the conclusion was "Agent Engine doesn't forward stdout", the
> fix was a Cloud Logging client library, and the truth was one flag on a sink.
>
> ```bash
> gcloud logging sinks describe _Default --project=$GOOGLE_CLOUD_PROJECT   # disabled: true is the bug
> gcloud logging sinks update _Default --no-disabled --project=$GOOGLE_CLOUD_PROJECT
> ```
>
> Sink changes take a few minutes to propagate, and entries written in the meantime are lost.

#### Log fields

Every event is one JSON object with these keys (exact set depends on which function emitted it):

| Field | Emitted by | Description |
|---|---|---|
| `severity` | all | `INFO` or `ERROR`; a Cloud Logging reserved field, filterable as `severity=ERROR` |
| `agent_name` | all | Always `root_agent`, in every project generated from this template — so it does **not** identify one agent in a shared project. `read_logs.sh` scopes by `reasoning_engine_id` instead |
| `event` | all | Event name: `<tool>.start` / `.end` / `.error`, or `model.usage` |
| `duration_ms` | `@instrument` | Wall-clock time for the call |
| `outcome` | `@instrument` (`.end`) | Always `success` — failures are a separate `.error` event instead |
| `error` | `@instrument` (`.error`) | `str(exception)` |
| `args`, `kwargs` | `@instrument` (`.start`) | The call's arguments, PII-redacted |
| `prompt_tokens`, `candidates_tokens`, `total_tokens` | `log_model_usage` | From the ADK event's `usage_metadata` |

See [Cloud Logging query examples](README.md#cloud-logging-query-examples) in `README.md` for
filters using these fields.

### How to modify prompts

1. Edit or add a `.md` file in `prompts/system/` or `prompts/tasks/`
2. If adding a new file, register it in `prompts/prompts.yaml` under the relevant agent
3. Run `make dev` and verify the agent behaves as expected
4. Add a promptfoo test case in `tests/evals/promptfoo.yaml` if the change affects safety or key behaviour

### How to add a sub-agent

1. Add an entry in `prompts/prompts.yaml` for the new agent name
2. Define the agent in `agent/agent.py` using standard ADK `Agent()` syntax
3. Wire it to `root_agent` via `sub_agents=[new_agent]` (ADK handles routing)

No custom classes, no inheritance — pure ADK syntax only.

### Code conventions

- **No `print()` in Python package code** — use `logging`
- **Conventional commits**: `feat(scope): description` — enforced by commitizen locally and
  by `lint-pr.yml` on the PR title (squash merges use the title, not your commit messages)
- **Pre-commit hooks**: ruff (lint + format), pyright, detect-secrets, markdownlint
  - Run `make pre-commit` before committing; never use `--no-verify`
- **CHANGELOG**: update `CHANGELOG.md` under `[Unreleased]` for every user-facing change

### Pre-commit (required — always fix before committing)

```bash
make pre-commit   # runs all hooks
```

- If ruff fails: run `make format` then `make lint` — ruff autofixes most issues
- If pyright fails: fix the type errors it reports
- If detect-secrets fails: make sure you have not committed credentials
- **Never use `git commit --no-verify`** — this bypasses safety checks

### Conventional commits (enforced twice — locally and in CI)

Format: `type(scope): description`

Allowed types: `build`, `bump`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`, `refactor`,
`revert`, `style`, `test`.

```text
feat(agent): add calendar lookup tool
fix(prompts): correct safety guidelines for PII handling
chore(deps): bump google-adk to 1.1.0
docs(readme): update deployment instructions
test(evals): add promptfoo test for jailbreak via roleplay
refactor(deployment): simplify config dataclass
```

Two things enforce this, and both matter:

- The **`commit-msg` hook** (commitizen) rejects non-conforming *commit messages* locally.
- **`lint-pr.yml`** checks the **PR title** in CI. This is not redundant: a squash merge
  discards the branch's commit messages and uses the PR title as the subject of the commit
  that lands on `main` — the one `cz bump` reads to build `CHANGELOG.md`. The local hook is
  also bypassable with `--no-verify` or by committing through the GitHub web UI.

Both accept the same set of types, so a message the hook accepts is always a valid PR title.

### CHANGELOG (update for every user-facing change)

Add an entry under `[Unreleased]` in `CHANGELOG.md` before committing. Use Keep a Changelog format:

```markdown
## [Unreleased]

### Added
- Calendar lookup tool powered by Google Calendar API

### Fixed
- Web search stub now includes query in snippet for easier local debugging
```

Run `cz bump` (via `uv run cz bump`) to cut a release and move unreleased entries to a dated section.

### Things that will bite you

- **`gcloud auth login` is not enough to deploy locally.** `vertexai.init()` reads
  Application Default Credentials, which that command does not refresh. Without
  `gcloud auth application-default login` the deploy fails with a `RefreshError` *after*
  the agent has been pickled and uploaded.
- **Local runs need `GOOGLE_GENAI_USE_VERTEXAI=TRUE` or a `GOOGLE_API_KEY`.** With neither,
  google-genai uses the AI Studio backend and fails with `No API key was provided` even
  though ADC is valid.
- **The agent's model access is a Google-managed default.** It comes from
  `roles/aiplatform.agentDefaultAccess` on the project's agent principalSet, which no
  repository manages (see [Runtime identity](#runtime-identity)). If it is removed, every
  request fails with `PermissionDenied` while logs and traces keep working.
- **The container's Python travels with every deploy.** The SDK's `update()` never sends
  `python_version`, OpenTofu cannot set it (the API rejects a `package_spec` without the
  pickle), and an engine without one builds on 3.10, where the build fails with
  `No matching distribution found for google-adk==2.x`. `deployment/python_version.py`
  adds the local `major.minor` to the update request. It wraps a private SDK function, so
  bumping `google-cloud-aiplatform` means `tests/unit/test_python_version.py` must still pass.
- **`deploy.py` never creates an engine.** Without `AGENT_ENGINE_RESOURCE_NAME` it stops
  before uploading anything. Run `make deploy-<env>`, which applies `infra/agent/` first and
  passes the engine's name; grants can still take a minute or two to propagate, which is why
  the health check retries.
- **Replacing the engine replaces the agent's identity.** A new `region`, or destroying the
  engine, gives the next apply a new engine and a new principal. Sessions on the old one are
  gone; the grants move with the apply.
- **An engine deleted outside OpenTofu leaves stale state.** The next apply creates a new one,
  with a new identity. Delete engines through `tofu destroy`, not the console.
- **Deploying an engine created outside OpenTofu makes a second one.** Adopt it with
  `make infra-import` first, or the first `make deploy-*` creates another engine next to it.
- **Applying the grants needs project IAM rights.** `make infra-apply` adds project-level
  bindings, so the deployer needs `roles/resourcemanager.projectIamAdmin` or owner, on top
  of what the deploy itself needs.
- **CI's buckets must use uniform bucket-level access.** CI logs in as a federated
  principal, and Cloud Storage rejects its writes to a bucket with fine-grained ACLs: the
  upload fails with a bare `412` although every IAM grant is in place. Buckets made by the
  old `setup_gcp.sh` (`gsutil mb` without `-b on`) have fine-grained ACLs; switch them with
  `gcloud storage buckets update gs://<bucket> --uniform-bucket-level-access`, and give the
  project's owners, editors and viewers `legacyObjectOwner`/`legacyObjectReader` on the
  bucket to keep the object access the default ACL gave them.
- **Missing logs are usually the project's log sink, not the agent.** A disabled `_Default`
  sink discards every non-audit entry however it was written, including a direct
  `gcloud logging write`. Check `gcloud logging sinks describe _Default` first.
- **CI can write only to `<agent>/` in the staging bucket.** The folder is the project name in
  `pyproject.toml` (`gcs_dir_name`) and the grant's condition uses `AGENT_SLUG` from the
  Makefile. If they differ, every CI deploy fails with a `403` on upload;
  `tests/unit/test_agent_slug.py` checks they match. Renaming the project means renaming both.
- **The staging bucket and state bucket are shared by every agent in the project.**
  `setup_gcp.sh` saying "already exists, skipping" is the intended way a second agent joins.
  Deleting either during a cleanup breaks sibling agents.
- **Each agent needs its own state prefix.** The prefix is `<agent>/<env>` from
  `AGENT_SLUG` in the Makefile. Two repos with the same prefix share one state file, and
  each apply then removes the other's grants.
- **The deployed container installs exactly what `uv.lock` pins.** `deploy.py` exports its
  `requirements` from the lock, because the agent is pickled against the local versions and a
  newer google-adk or cloudpickle in the container fails at request time. Deploy through
  `uv run` so the environment matches the lock, and commit `uv.lock` after changing
  dependencies.
- **Nothing under `agent/` except `agent/agent.py` may import `deployment` or `tests`.**
  Only `agent` and `prompts` are shipped. The container imports `agent/__init__.py` and the
  tool modules by reference, but never `agent/agent.py`, whose `resolve_model()` call is
  evaluated at pickle time. A `deployment` import elsewhere deploys green and fails on the
  first request; `tests/unit/test_pickle_boundary.py` catches it in CI.
- **Non-Google model providers fail only after deploying.** No API key reaches the deployed
  container, so a deploy with `MODEL_PROVIDER=anthropic` or `openai` goes green and every request
  then fails. Local runs and tests pass because `.env` supplies the key.
- **A squash merge uses the PR title, not your commit messages.** That title is what
  `cz bump` reads to build the changelog, which is why `lint-pr.yml` checks it separately
  from the local commit-msg hook.

### Definition of done

- [ ] `make pre-commit` passes — never `--no-verify`
- [ ] `make test` passes, with combined-suite coverage at or above the configured floor
- [ ] `make eval` reviewed if prompts, tools or safety behaviour changed
- [ ] `CHANGELOG.md` updated under `[Unreleased]`
- [ ] PR title is a valid conventional commit
- [ ] If deployed: `make health-check` passes, and `make logs` / `make traces` show the
      expected events for a tool call
