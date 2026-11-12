<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/banner-dark.svg">
  <img alt="{{ cookiecutter.project_name|e }} — {{ cookiecutter.project_description|e }}" src="docs/assets/banner-light.svg">
</picture>

{%- set repo = cookiecutter.github_org ~ '/' ~ cookiecutter.project_slug %}
{%- set shield_license = cookiecutter.open_source_license.replace('-', '--') %}

[![CI](https://img.shields.io/github/actions/workflow/status/{{repo}}/ci.yml?branch=main&style=flat&label=CI&labelColor=0E0E10&color=0E0E10)](https://github.com/{{repo}}/actions/workflows/ci.yml)
[![Deploy](https://img.shields.io/github/actions/workflow/status/{{repo}}/deploy.yml?branch=main&style=flat&label=deploy&labelColor=0E0E10&color=0E0E10)](https://github.com/{{repo}}/actions/workflows/deploy.yml)
{% if cookiecutter.open_source_license == 'Proprietary' -%}
![License](https://img.shields.io/badge/license-Proprietary-0E0E10?style=flat&labelColor=0E0E10)
{%- else -%}
[![License](https://img.shields.io/badge/license-{{shield_license}}-0E0E10?style=flat&labelColor=0E0E10)](LICENSE)
{%- endif %}
[![Python](https://img.shields.io/badge/python-{{cookiecutter.python_version}}-0E0E10?style=flat&labelColor=0E0E10&logo=python&logoColor=white)](pyproject.toml)
[![uv](https://img.shields.io/badge/uv-managed-0E0E10?style=flat&labelColor=0E0E10&logo=uv&logoColor=white)](https://docs.astral.sh/uv/)
[![Ruff](https://img.shields.io/badge/ruff-checked-0E0E10?style=flat&labelColor=0E0E10&logo=ruff&logoColor=white)](https://docs.astral.sh/ruff/)
[![Pyright](https://img.shields.io/badge/pyright-checked-0E0E10?style=flat&labelColor=0E0E10)](https://microsoft.github.io/pyright/)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-0E0E10?style=flat&labelColor=0E0E10&logo=pre-commit&logoColor=white)](.pre-commit-config.yaml)
[![detect-secrets](https://img.shields.io/badge/detect--secrets-scanned-0E0E10?style=flat&labelColor=0E0E10)](https://github.com/Yelp/detect-secrets)
[![Agent Engine](https://img.shields.io/badge/Vertex%20AI-Agent%20Engine-0E0E10?style=flat&labelColor=0E0E10&logo=googlecloud&logoColor=white)](https://cloud.google.com/vertex-ai/docs/agents/overview)

---

**{{cookiecutter.project_description}}**
Built with [Google ADK](https://google.github.io/adk-docs/) and deployed on [Vertex AI Agent Engine](https://cloud.google.com/vertex-ai/docs/agents/overview).

## Start here

Point your coding agent at **[AGENTS.md](./AGENTS.md)** and tell it what you want to change.

```text
Read AGENTS.md, then add a tool that looks up an order by ID
and deploy it to dev.
```

That file is the single source of truth for this repository: setup, the make targets to use
instead of raw commands, how to add a tool or a sub-agent, what the agent runs as once
deployed, and where its logs and traces go. It ends with the traps that cost real debugging
time and a definition of done.

The rest of this page is the overview.

---

## Architecture

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#FFFFFF","primaryTextColor":"#202124","primaryBorderColor":"#DADCE0","lineColor":"#5F6368","secondaryColor":"#F8F9FA","tertiaryColor":"#F8F9FA","clusterBkg":"#F8F9FA","clusterBorder":"#DADCE0","edgeLabelBackground":"#FFFFFF"},"flowchart":{"curve":"basis","nodeSpacing":40,"rankSpacing":64,"useMaxWidth":true}} }%%
flowchart TD
    subgraph trusted["Your machine — developer credentials"]
        DEV["make dev<br/>adk web :8000"] --> ROOT["root_agent"]
        ROOT --> TOOLS["agent/tools/<br/>@instrument"]
        ROOT --> PROMPTS["prompts/ + prompts.yaml"]
    end

    subgraph github["GitHub — no GCP credentials until the gate"]
        PR["pull request"] --> CHECKS["ci.yml · eval.yml · lint-pr.yml<br/>lint · types · tests · red-team"]
        CHECKS --> REVIEW{{"Review and merge<br/>— human approval —"}}
        REVIEW -->|"push to main, CI green"| DEPLOY["deploy.yml"]
        SEC["security.yml<br/>CodeQL · pip-audit · secret scan"]
        DRIFT["cruft-check.yml<br/>template drift"]
    end

    subgraph gcp["Google Cloud — the agent's own Agent Identity"]
        ENGINE["Vertex AI Agent Engine<br/>runs as its Agent Identity"]
        GRANTS["infra/agent<br/>OpenTofu creates it, grants its roles"] -.-> ENGINE
        ENGINE --> MODEL{MODEL_PROVIDER}
        MODEL --> G["Gemini 2.5 Pro"]
        MODEL --> CL["Claude via LiteLLM"]
        MODEL --> OAI["GPT-4o via LiteLLM"]
        ENGINE --> LOG["Cloud Logging<br/>reasoning_engine_stdout"]
        ENGINE --> TRACE["Cloud Trace<br/>Agent Engine telemetry"]
    end

    DEPLOY -->|"WIF, no key"| ENGINE
    CLIENT["API consumer"] -->|REST| ENGINE

    classDef approval fill:#1A73E8,stroke:#1A73E8,color:#FFFFFF;
    class REVIEW approval;
```

The blue node is the only point a human approves: everything upstream of it runs without
GCP credentials. The deployed agent runs under its own Agent Identity, which holds only the
roles `infra/agent` grants it. See [Runtime identity](AGENTS.md#runtime-identity).

## Quickstart

### Prerequisites

- Python {{cookiecutter.python_version}}+, [uv](https://docs.astral.sh/uv/), Node.js 22+ (promptfoo requires it)
- [gcloud CLI](https://cloud.google.com/sdk/docs/install) authenticated
- [OpenTofu](https://opentofu.org) 1.8+ to deploy (it grants the agent identity its roles)

### Local development

```bash
make install              # install dependencies
cp .env.example .env      # configure environment variables
make dev                  # run at http://localhost:8000
```

### Run tests

```bash
make test                 # unit tests with coverage
make eval                 # promptfoo red-team evaluation
```

### Deploy to GCP

Deploying from your machine needs both `gcloud` credential stores: the CLI login and
Application Default Credentials. `gcloud auth login` does **not** refresh ADC, and
`vertexai.init()` reads ADC — with only the first, a deploy fails partway with a
`RefreshError`.

```bash
gcloud auth login
gcloud auth application-default login

make setup-gcp ENV=dev    # one-time GCP bootstrap for the dev project (APIs; checks the shared buckets)
make setup-gcp ENV=prod   # same, for the prod project (ENV defaults to prod if omitted)
make deploy-dev           # OpenTofu: engine, identity, roles; ship the code; health-check
make deploy-prod          # same, for prod
```

`make deploy-*` asks you to confirm the OpenTofu plan before it creates or grants anything.
Applying it needs an account that may change project IAM. Dev and prod get separate engines
from separate OpenTofu state, so nothing about the engine goes into `.env`.

`dev` and `prod` deploy via separate GitHub Environments with their own secrets and variables —
see [Required GitHub Environments](AGENTS.md#required-github-environments) in `AGENTS.md` for
exactly what to configure and where `setup-gcp`'s output goes.

## Make targets

| Target | Description |
|---|---|
| `make dev` | Run agent locally at http://localhost:8000 |
| `make test` | Unit tests with coverage |
| `make test-integration` | Integration tests only |
| `make eval` | Prompt security evaluation (promptfoo) |
| `make lint` | Ruff lint check |
| `make format` | Ruff formatter |
| `make typecheck` | Pyright |
| `make deploy-dev` | Apply `infra/agent` (engine, identity, roles), ship the code, health-check |
| `make deploy-prod` | Same, for prod |
| `make infra-apply ENV=dev\|prod` | Create or update the engine and its grants only |
| `make infra-import ENV=dev\|prod ENGINE=<name>` | One-time: adopt an engine created outside OpenTofu |
| `make deploy-code ENV=dev\|prod` | Ship the code to the existing engine without applying (what CI runs) |
| `make infra-test` | OpenTofu fmt, validate and tests (offline) |
| `make rollback REF=<tag> [ENV=prod\|dev]` | Redeploy a previous git ref against the existing Agent Engine resource |
| `make health-check` | Standalone smoke test against the deployed Agent Engine resource (no fresh deploy) |
| `make logs` | Stream Cloud Logging |
| `make traces` | List this agent's Cloud Trace spans |
| `make setup-gcp [ENV=dev\|prod]` | One-time GCP bootstrap (default: prod) |
| `make setup-monitoring` | One-time Cloud Monitoring dashboard + alert policy bootstrap |
| `make pre-commit` | Run all pre-commit hooks |
| `make clean` | Remove caches, coverage output and build artefacts |
| `make help` | List every target with its description |

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | Deploy | GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | Deploy | Vertex AI region (default: `europe-west1`) |
| `GCS_STAGING_BUCKET` | No | Defaults to `gs://$GOOGLE_CLOUD_PROJECT-agent-staging`; `gs://` optional |
| `AGENT_ENGINE_RESOURCE_NAME` | No | Set by `make deploy-*` from the OpenTofu output; only for running `deploy.py` or the health check by hand |
| `STATE_BUCKET` | No | OpenTofu state bucket; defaults to `$GOOGLE_CLOUD_PROJECT-agents-state` |
| `MODEL_PROVIDER` | No | `google` \| `anthropic` \| `openai` \| `litellm` |
| `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY` | No | Set to `true` on deploy: Agent Engine's built-in tracing |
| `OTEL_SEMCONV_STABILITY_OPT_IN` | No | Set to `gen_ai_latest_experimental` on deploy: the latest GenAI semantic conventions, as Google's `AdkApp` setup does |
| `CLOUD_TRACE_ENABLED` | No | Our own span exporter, local runs only (it fails under Agent Identity) |
| `OTEL_EXPORTER_GCP_TRACE_PROJECT_ID` | With `CLOUD_TRACE_ENABLED` | Project our exporter writes to |
| `GOOGLE_API_KEY` | Local dev | Not needed on GCP (uses ADC) |
| `ANTHROPIC_API_KEY` | If provider=anthropic | |
| `OPENAI_API_KEY` | If provider=openai | |
| `SERPAPI_API_KEY` | No | Enables live web search; omit for stub |

## Model providers

Set `MODEL_PROVIDER` in `.env`:

| Value | Model |
|---|---|
| `google` (default) | Gemini 2.5 Pro |
| `anthropic` | Claude Opus 4.8 via LiteLLM |
| `openai` | GPT-4o via LiteLLM |
| `litellm` | Any model — set `LITELLM_MODEL` |

Only `google` works on the deployed agent for now: the other providers' API keys are not forwarded
to Agent Engine. See [Multi-provider model selection](AGENTS.md#multi-provider-model-selection).

## Logging and traces

```bash
make logs     # read this agent's Cloud Logging entries (requires GOOGLE_CLOUD_PROJECT in .env)
make traces   # list this agent's Cloud Trace spans
```

`agent/observability.py` emits structured JSON events (tool calls, token usage) via
`log_event`/`@instrument`, and a Cloud Trace span per instrumented call. Logs need no setup;
tracing is enabled on the deployed agent and off locally, so `make dev` just prints to stdout.

See [Observability](AGENTS.md#observability) in `AGENTS.md` for the field reference, the two
variables tracing needs, and what to check first when logs appear to be missing.

### Cloud Logging query examples

Run these in [Logs Explorer](https://console.cloud.google.com/logs) or via `gcloud logging read`.
Scope by `reasoning_engine_id` to isolate one agent — the log names are shared by every engine
in the project, and `jsonPayload.agent_name` is `root_agent` in all of them:

```bash
ENGINE_ID=$(cat .agent_engine_resource | sed 's#.*/##')
STDOUT='logName="projects/'$GOOGLE_CLOUD_PROJECT'/logs/aiplatform.googleapis.com%2Freasoning_engine_stdout"'

# Every structured event this agent emits
gcloud logging read "$STDOUT AND resource.labels.reasoning_engine_id=\"$ENGINE_ID\"" --project=$GOOGLE_CLOUD_PROJECT --limit=50

# A specific tool's calls (start/end/error events all share its name as a prefix)
gcloud logging read "$STDOUT AND jsonPayload.event=~\"^web_search\.\"" --project=$GOOGLE_CLOUD_PROJECT

# Token usage per request
gcloud logging read "$STDOUT AND jsonPayload.event=\"model.usage\"" --project=$GOOGLE_CLOUD_PROJECT
```

## Monitoring and alerting

```bash
make setup-monitoring   # one-time: dashboard + error-rate/latency alert policies
```

Builds on Agent Engine's built-in `reasoning_engine/*` metrics (request count, latency, CPU/memory
allocation) — see [Monitoring & alerting](AGENTS.md#monitoring--alerting) in `AGENTS.md` for the
metric reference, alert thresholds, and how to attach an email or Slack notification channel.

## Security

Prompt injection, jailbreak, and PII tests run automatically on every PR via [promptfoo](https://promptfoo.dev). Add test cases in `tests/evals/promptfoo.yaml`. See [SECURITY.md](SECURITY.md) for the vulnerability disclosure policy.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). AI assistants: read [AGENTS.md](AGENTS.md) for full project context and working instructions.
