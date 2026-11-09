<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/banner-dark.svg">
  <img alt="ADK Agent Deployment Template — generate a production-ready Google ADK agent repository and deploy it to Vertex AI Agent Engine, with observability, evals and CI already wired up." src="docs/assets/banner-light.svg">
</picture>

[![CI](https://img.shields.io/github/actions/workflow/status/GEG-ETHZ/agent-deployment-template/ci.yml?branch=main&style=flat&label=CI&labelColor=0E0E10&color=0E0E10)](https://github.com/GEG-ETHZ/agent-deployment-template/actions/workflows/ci.yml)
[![Template validation](https://img.shields.io/github/actions/workflow/status/GEG-ETHZ/agent-deployment-template/validate-template.yml?branch=main&style=flat&label=template&labelColor=0E0E10&color=0E0E10)](https://github.com/GEG-ETHZ/agent-deployment-template/actions/workflows/validate-template.yml)
[![License](https://img.shields.io/badge/license-MIT-0E0E10?style=flat&labelColor=0E0E10)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-0E0E10?style=flat&labelColor=0E0E10&logo=python&logoColor=white)](pyproject.toml)
[![uv](https://img.shields.io/badge/uv-managed-0E0E10?style=flat&labelColor=0E0E10&logo=uv&logoColor=white)](https://docs.astral.sh/uv/)
[![Ruff](https://img.shields.io/badge/ruff-checked-0E0E10?style=flat&labelColor=0E0E10&logo=ruff&logoColor=white)](https://docs.astral.sh/ruff/)
[![Pyright](https://img.shields.io/badge/pyright-checked-0E0E10?style=flat&labelColor=0E0E10)](https://microsoft.github.io/pyright/)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-0E0E10?style=flat&labelColor=0E0E10&logo=pre-commit&logoColor=white)](.pre-commit-config.yaml)
[![detect-secrets](https://img.shields.io/badge/detect--secrets-scanned-0E0E10?style=flat&labelColor=0E0E10)](https://github.com/Yelp/detect-secrets)
[![cruft](https://img.shields.io/badge/cruft-tracked-0E0E10?style=flat&labelColor=0E0E10)](https://cruft.github.io/cruft/)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/hero-dark.svg">
  <img alt="One template, many agents, kept in sync. agent-deployment-template is a cookiecutter template holding what every agent gets: a Google ADK agent with tools and prompts; pytest, pyright, promptfoo evals and CodeQL; CI/CD that deploys only after CI passes; JSON logs and Cloud Trace spans. cruft create stamps an agent repository from it once, after eleven questions, and cruft update keeps each repository in step with every release; cruft-check.yml flags one that falls behind. After review, merge and CI, each repository deploys to Vertex AI Agent Engine in dev and prod, running as agent-engine-sa with logs and traces." src="docs/assets/hero-light.svg">
</picture>

---

**Answer eleven questions and get an agent repository that already knows how to deploy
itself, run as its own service account, and show you what it did afterwards.**

## Start here

Generate a project, then point your coding agent at **[AGENTS.md](./AGENTS.md)** in the
repository it just made, and tell it what you want the agent to do.

```text
Read AGENTS.md and get this deployed to our dev project. I want an agent
that can answer questions about our internal runbooks.
```

That file is written for exactly this. It covers the prerequisites worth checking before
anything is provisioned, the two credential stores a local deploy needs, the one IAM grant
that fails only after the agent has been uploaded, and how to tell whether the thing
actually works once it is running.

The rest of this page is what the agent is working from.

---

## What you get

Running `cookiecutter` against this template generates a fully configured Python repository with:

- Google ADK `root_agent` that runs out of the box with `make dev`
- Structured prompt system — compose prompts from `.md` files via a YAML registry
- Multi-provider model support: Gemini, Claude (via LiteLLM), GPT-4o (via LiteLLM)
- One-command deploy to Vertex AI Agent Engine (`make deploy-prod`)
- GitHub Actions: CI, security audit, prompt red-team eval, and deployment
- Pre-commit hooks: ruff, pyright, detect-secrets, markdownlint, commitizen
- Promptfoo red-team evaluation suite (prompt injection, jailbreak, PII tests)
- Cloud Logging and Cloud Trace integration via `make logs` / `make traces`
- `AGENTS.md` with full contributor and AI assistant instructions (`CLAUDE.md` points at it)
- `.claude/commands/` slash commands: `/deploy`, `/eval`, `/logs`

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Node.js 22+ (promptfoo requires it)
- [gcloud CLI](https://cloud.google.com/sdk/docs/install) (for deployment)
- [cruft](https://cruft.github.io/cruft/) — `pip install cruft` (wraps cookiecutter and tracks
  the template version so you can pull in updates later; plain
  `pip install cookiecutter` also works if you don't need update tracking)

## Quickstart

```bash
# 1. Generate your agent project (cruft is the canonical way — it records
#    which template commit you generated from, in .cruft.json)
cruft create gh:your-org/agent-deployment-template

# 2. Enter the generated project
cd your-agent-name

# 3. Configure environment
cp .env.example .env
# Edit .env — fill in GOOGLE_CLOUD_PROJECT and GOOGLE_API_KEY at minimum

# 4. Run locally
make dev   # → http://localhost:8000
```

### Keeping a generated project in sync with the template

Every generated project has a `.cruft.json` pinning the template commit it was
created from. When the template gains new features or fixes, pull them into
your project:

```bash
cruft check    # is this project behind the template?
cruft update   # apply the diff — resolve conflicts like a merge
```

## Generation flow

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#FFFFFF","primaryTextColor":"#202124","primaryBorderColor":"#DADCE0","lineColor":"#5F6368","secondaryColor":"#F8F9FA","tertiaryColor":"#F8F9FA","clusterBkg":"#F8F9FA","clusterBorder":"#DADCE0","edgeLabelBackground":"#FFFFFF"},"flowchart":{"curve":"basis","nodeSpacing":40,"rankSpacing":64,"useMaxWidth":true}} }%%
flowchart LR
    A["cookiecutter command"] --> B["cookiecutter.json<br/>answer prompts"]
    B --> C["pre_gen_project.py<br/>validate inputs"]
    C --> D["Render template files"]
    D --> E["post_gen_project.py<br/>git init · uv sync · pre-commit install"]
    E --> F["Your agent repo<br/>ready to develop and deploy"]
```

## Generated repo architecture

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
        REVIEW -->|push to main| DEPLOY["deploy.yml"]
        SEC["security.yml<br/>CodeQL · pip-audit · secret scan"]
        DRIFT["cruft-check.yml<br/>template drift"]
    end

    subgraph gcp["Google Cloud — agent-engine-sa"]
        ENGINE["Vertex AI Agent Engine<br/>runs as agent-engine-sa"]
        ENGINE --> MODEL{MODEL_PROVIDER}
        MODEL --> G["Gemini 2.5 Pro"]
        MODEL --> CL["Claude via LiteLLM"]
        MODEL --> OAI["GPT-4o via LiteLLM"]
        ENGINE --> LOG["Cloud Logging<br/>reasoning_engine_stdout"]
        ENGINE --> TRACE["Cloud Trace<br/>one span per tool call"]
        LOG --> LOGSH["make logs"]
        TRACE --> TRACESH["make traces"]
    end

    DEPLOY -->|GCP_SA_KEY · actAs| ENGINE
    CLIENT["API consumer"] -->|REST| ENGINE

    classDef approval fill:#1A73E8,stroke:#1A73E8,color:#FFFFFF;
    class REVIEW approval;
```

The blue node is the only point a human approves: everything upstream of it runs without
GCP credentials, and everything downstream runs as `agent-engine-sa`.

## Cookiecutter variables

| Variable | Default | Description |
| --- | --- | --- |
| `project_name` | `My ADK Agent` | Human-readable project name |
| `project_slug` | auto from name | Directory name and Python package name |
| `project_description` | — | One-line description |
| `author_name` | — | Your name |
| `author_email` | — | Your email |
| `github_org` | `your-org` | GitHub organisation |
| `gcp_project_id` | `my-gcp-project` | GCP project ID (update in `.env`) |
| `gcp_location` | `europe-west1` | Vertex AI region |
| `model_provider` | `google` | Default model provider |
| `python_version` | `3.11` | Python version |
| `open_source_license` | `MIT` | License type (`MIT`, `Apache-2.0`, `Proprietary`) |

## Contributing to the template

See [AGENTS.md](AGENTS.md) for contributor instructions (also read automatically by AI assistants).

```bash
make install    # install template dev dependencies
make validate   # generate test project and run its tests
make pre-commit # run all hooks
```
