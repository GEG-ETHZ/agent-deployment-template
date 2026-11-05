.PHONY: install lint format typecheck validate pre-commit help

help:
	@echo ""
	@echo "agent-deployment-template — available targets"
	@echo ""
	@echo "  install     Install dev dependencies and git hooks for the template repo"
	@echo "  lint        Lint hooks/ with ruff"
	@echo "  format      Format hooks/ with ruff"
	@echo "  typecheck   Type-check hooks/ with pyright"
	@echo "  validate    Generate a test project and run its lint + unit + integration tests"
	@echo "  pre-commit  Run all pre-commit hooks on all files"
	@echo ""

install:
	uv sync
	uv run pre-commit install
	uv run pre-commit install --hook-type commit-msg

lint:
	uv run ruff check hooks/

format:
	uv run ruff format hooks/

typecheck:
	uv run pyright hooks/

validate:
	@echo "Generating test project from template..."
	rm -rf /tmp/cc-validate
	cookiecutter . --no-input \
		--output-dir /tmp/cc-validate \
		project_name="Test Agent" \
		author_email="test@example.com" \
		gcp_project_id="test-project-123"
	@echo "Running lint and tests in generated project..."
	cd /tmp/cc-validate/test-agent && uv sync --frozen
	cd /tmp/cc-validate/test-agent && uv run ruff check .
	cd /tmp/cc-validate/test-agent && uv run ruff format --check .
	cd /tmp/cc-validate/test-agent && uv run pytest tests/unit -v --no-cov
	cd /tmp/cc-validate/test-agent && uv run pytest tests/integration -v --tb=short --no-cov
	cd /tmp/cc-validate/test-agent && make infra-test
	@echo ""
	@echo "Template validation passed."
	rm -rf /tmp/cc-validate

pre-commit:
	uv run pre-commit run --all-files
