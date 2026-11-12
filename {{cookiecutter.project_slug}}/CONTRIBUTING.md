# Contributing to {{cookiecutter.project_name}}

## Local development setup

Prerequisites: Python {{cookiecutter.python_version}}+, uv, Node.js 22+ (promptfoo requires it), gcloud CLI

```bash
make install
cp .env.example .env   # fill in at minimum GOOGLE_CLOUD_PROJECT
gcloud auth application-default login   # Gemini on Vertex AI, and the eval's grader
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
make dev
```

See [AGENTS.md](AGENTS.md) for the full project reference (also read by AI assistants).

## Branch naming

| Prefix | Use for |
|---|---|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `chore/` | Dependency updates, tooling |
| `docs/` | Documentation only |
| `test/` | Tests only |
| `refactor/` | Code restructuring without behaviour change |

## Conventional commits (required)

Format: `type(scope): description`

```bash
feat(agent): add calendar lookup tool
fix(prompts): correct safety refusal wording
chore(deps): bump google-adk to 1.2.0
docs(readme): add traces section
```

Allowed types: `build`, `bump`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`, `refactor`,
`revert`, `style`, `test`.

The `commit-msg` pre-commit hook rejects non-conforming commit messages locally, and
`lint-pr.yml` applies the same rule to your **PR title** in CI — which matters because a
squash merge uses the PR title, not your commit messages, as the subject of the commit that
lands on `main`.

## Pull request requirements

- [ ] All CI checks pass
- [ ] One approval from a team member
- [ ] `CHANGELOG.md` updated under `[Unreleased]` for user-facing changes
- [ ] New tools have unit tests in `tests/unit/`
- [ ] Prompt changes have a corresponding `tests/evals/promptfoo.yaml` test case

## Adding a tool

1. Write the function in `agent/tools/` with type annotations and a docstring
2. Export it from `agent/tools/__init__.py`
3. Add it to `tools=[...]` in `agent/agent.py`
4. Add unit tests in `tests/unit/test_tools.py`

## Adding a prompt

1. Create or edit a `.md` file in `prompts/system/` or `prompts/tasks/`
2. Register it in `prompts/prompts.yaml`
3. Verify with `make dev`
4. Add a promptfoo eval case if the change affects safety behaviour
