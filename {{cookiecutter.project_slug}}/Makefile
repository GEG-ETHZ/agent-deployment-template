.PHONY: install dev lint format typecheck test test-unit test-integration eval \
        deploy-dev deploy-prod rollback health-check logs traces setup-gcp setup-monitoring \
        deploy-code infra-init infra-apply infra-import infra-test pre-commit clean help

-include .env
export

# OpenTofu that creates the agent's engine and Agent Identity and grants its roles. State
# sits in the bucket every agent of the project shares, one prefix per agent and env.
INFRA_DIR := infra/agent
AGENT_SLUG := {{cookiecutter.project_slug}}
STATE_BUCKET ?= $(GOOGLE_CLOUD_PROJECT)-agents-state
GOOGLE_CLOUD_LOCATION ?= europe-west1
STAGING_BUCKET = $(patsubst gs://%,%,$(or $(GCS_STAGING_BUCKET),$(GOOGLE_CLOUD_PROJECT)-agent-staging))
# The repository whose deploy.yml may ship this agent's code (grants in infra/agent/ci.tf).
# GitHub Actions sets it; locally it comes from the `origin` remote, empty without one.
GITHUB_REPOSITORY ?= $(shell git remote get-url origin 2>/dev/null | sed -E 's|^(git@github\.com:\|https://github\.com/)||; s|\.git$$||')
TOFU_VARS = -var="project_id=$(GOOGLE_CLOUD_PROJECT)" \
	-var="region=$(GOOGLE_CLOUD_LOCATION)" \
	-var="agent_slug=$(AGENT_SLUG)" \
	-var="staging_bucket=$(STAGING_BUCKET)" \
	-var="state_bucket=$(STATE_BUCKET)" \
	-var="github_repository=$(GITHUB_REPOSITORY)"
# The engine of the environment infra-init last selected, read from the OpenTofu state.
ENGINE_NAME = $$(tofu -chdir=$(INFRA_DIR) output -raw agent_resource_name)

help:
	@echo ""
	@echo "{{cookiecutter.project_name}} — available targets"
	@echo ""
	@echo "  install      Install all dependencies with uv"
	@echo "  dev          Run agent locally via adk web UI (http://localhost:8000)"
	@echo "  lint         Run ruff lint check"
	@echo "  format       Run ruff formatter"
	@echo "  typecheck    Run pyright type checker"
	@echo "  test              Run all tests with coverage (unit + integration)"
	@echo "  test-unit         Run unit tests only"
	@echo "  test-integration  Run integration tests (mocked LLM, no API keys needed)"
	@echo "  eval              Run promptfoo skill evaluations"
	@echo "  deploy-dev   Apply infra/agent (engine, identity, roles), ship the code, health-check"
	@echo "  deploy-prod  Same, for prod"
	@echo "  deploy-code  Ship the code to the existing engine, no apply (what CI runs): ENV=dev|prod"
	@echo "  infra-apply  Create or update the engine and its grants: make infra-apply ENV=dev|prod"
	@echo "  infra-import Adopt an existing engine: make infra-import ENV=dev ENGINE=projects/..."
	@echo "  infra-test   Run the OpenTofu tests (offline, mocked provider)"
	@echo "  rollback     Redeploy a previous git ref: make rollback REF=<tag> [ENV=prod|dev]"
	@echo "  health-check Run a standalone smoke test against the deployed Agent Engine resource"
	@echo "  logs         Stream Cloud Logging output for this agent"
	@echo "  traces       List this agent's Cloud Trace spans"
	@echo "  setup-gcp    One-time GCP bootstrap: make setup-gcp [ENV=dev|prod] (default: prod)"
	@echo "  setup-monitoring  One-time Cloud Monitoring dashboard + alert policy bootstrap"
	@echo "  pre-commit   Run all pre-commit hooks on all files"
	@echo "  clean        Remove build artefacts and caches"
	@echo ""

install:
	uv sync

dev:
	uv run adk web

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run pyright

test:
	uv run pytest

test-unit:
	uv run pytest tests/unit -v

test-integration:
	uv run pytest tests/integration -v --tb=short

eval:
	uv run python tests/evals/run_eval.py

# Apply first: OpenTofu creates the engine, which gives the agent its identity, and grants
# that identity its roles before any code runs. deploy-code then ships the code to it.
deploy-dev deploy-prod: deploy-%:
	$(MAKE) infra-apply ENV=$*
	$(MAKE) deploy-code ENV=$*

# Ship the code to the engine the ENV state names, then health-check it (retrying while
# new grants propagate). Reads the state, never applies: this is what deploy.yml runs.
deploy-code: infra-init
	engine="$(ENGINE_NAME)" && \
	AGENT_ENGINE_RESOURCE_NAME="$$engine" uv run python deployment/deploy.py --env $(ENV) && \
	AGENT_ENGINE_RESOURCE_NAME="$$engine" uv run python deployment/scripts/health_check.py

infra-init:
	@if [ "$(ENV)" != "dev" ] && [ "$(ENV)" != "prod" ]; then \
		echo "Usage: make infra-init ENV=dev|prod"; exit 1; \
	fi
	@if [ -z "$(GOOGLE_CLOUD_PROJECT)" ]; then \
		echo "GOOGLE_CLOUD_PROJECT is not set (.env or environment)"; exit 1; \
	fi
	tofu -chdir=$(INFRA_DIR) init -reconfigure -input=false \
		-backend-config="bucket=$(STATE_BUCKET)" \
		-backend-config="prefix=$(AGENT_SLUG)/$(ENV)"

infra-apply: infra-init
	tofu -chdir=$(INFRA_DIR) apply -input=false $(TOFU_VARS)

# One-time: bring an engine created outside OpenTofu under its state, so it keeps its ID
# and identity instead of a second engine being created next to it.
infra-import: infra-init
	@if [ -z "$(ENGINE)" ]; then \
		echo "Usage: make infra-import ENV=dev|prod ENGINE=projects/<p>/locations/<l>/reasoningEngines/<id>"; \
		exit 1; \
	fi
	tofu -chdir=$(INFRA_DIR) import -input=false $(TOFU_VARS) \
		google_vertex_ai_reasoning_engine.agent "$(ENGINE)"

infra-test:
	tofu -chdir=$(INFRA_DIR) fmt -check -recursive
	tofu -chdir=$(INFRA_DIR) init -backend=false -input=false
	tofu -chdir=$(INFRA_DIR) validate
	tofu -chdir=$(INFRA_DIR) test

rollback:
	@if [ -z "$(REF)" ]; then \
		echo "Usage: make rollback REF=<tag> [ENV=prod|dev]"; \
		exit 1; \
	fi
	@echo "Rolling back to $(REF) (env: $(or $(ENV),prod))..."
	git fetch --tags --quiet
	$(MAKE) infra-init ENV=$(or $(ENV),prod)
	@engine="$(ENGINE_NAME)"; \
	branch=$$(git rev-parse --abbrev-ref HEAD); \
	git checkout $(REF) && \
	AGENT_ENGINE_RESOURCE_NAME="$$engine" uv run python deployment/deploy.py --env $(or $(ENV),prod); \
	status=$$?; \
	git checkout "$$branch"; \
	[ $$status -eq 0 ] || exit $$status; \
	AGENT_ENGINE_RESOURCE_NAME="$$engine" uv run python deployment/scripts/health_check.py

health-check:
	uv run python deployment/scripts/health_check.py

logs:
	bash deployment/scripts/read_logs.sh

traces:
	uv run python deployment/scripts/read_traces.py

setup-gcp:
	bash deployment/scripts/setup_gcp.sh $(or $(ENV),prod)

setup-monitoring:
	bash deployment/scripts/setup_monitoring.sh

pre-commit:
	uv run pre-commit run --all-files

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov .mypy_cache
