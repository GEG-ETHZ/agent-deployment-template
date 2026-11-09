# AGENTS.md — ADK Agent Deployment Template

Single source of truth for working on this repository — for people and for AI
assistants alike. `CLAUDE.md` points here and holds no content of its own.

## Part A — using this

### What this repository is

This is a **cookiecutter template** repository. Running `cookiecutter .` (or `cookiecutter gh:your-org/agent-deployment-template`) generates a new, fully configured Google ADK agent project.

**Critical rule**: all files inside `{{cookiecutter.project_slug}}/` are template files that become the generated project. They contain Jinja2 variables like `{{cookiecutter.project_name}}`. Do not treat them as live, runnable code — they are templates. Running Python files directly from this directory will fail because the cookiecutter variables are not substituted.

### Setup

Prerequisites: Python 3.11+, `uv`, Node.js 22+ (promptfoo requires it), `cookiecutter`,
OpenTofu 1.13+ (the generated `infra/agent/` is tested offline by `make validate`)

```bash
make install    # install dev dependencies + pre-commit/commit-msg git hooks
make validate   # generate a test project and verify it compiles + tests pass
```

### Make targets

| Target | Description |
| --- | --- |
| `make install` | Install dev dependencies with uv, then install the pre-commit and commit-msg git hooks |
| `make lint` | Ruff lint check (excludes generated template dir) |
| `make format` | Ruff format |
| `make typecheck` | Pyright on hooks/ |
| `make validate` | Generate test project + run its lint and unit tests |
| `make pre-commit` | Run all pre-commit hooks on all files |

### GitHub Actions (template repo)

| Workflow | Trigger | What it does |
| --- | --- | --- |
| `ci.yml` | push + PR | Lints hooks/, validates markdown, checks cookiecutter.json |
| `validate-template.yml` | push + PR | Generates a project via cookiecutter and runs its unit tests; generates one via cruft and checks that `cruft update` applies a template change |
| `lint-pr.yml` | PR open/edit | Checks PR title is a valid conventional commit |

### Template Versioning

This template is versioned independently from any generated project. Version bumps follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html):

- **MAJOR** — a change that breaks existing generated projects on `cruft update` (renamed/removed
  cookiecutter variable, restructured generated file layout, removed make target a workflow depends on)
- **MINOR** — a backward-compatible addition (new cookiecutter variable with a sane default, new
  workflow, new optional feature). Existing generated projects keep working untouched after `cruft update`.
- **PATCH** — a fix or doc change with no effect on the generated project's structure or behavior

#### Cutting a release

1. Make sure every change since the last release is recorded under `[Unreleased]` in `CHANGELOG.md`
2. Rename `[Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD` (leave a fresh empty `[Unreleased]` above it)
3. Commit the CHANGELOG update
4. Tag the release commit: `git tag -a vX.Y.Z -m "vX.Y.Z: <one-line summary>"`
5. Push the tag with `git push --tags` (tags are how generated projects pin upgrades — see below)

#### How generated projects consume a release

A generated project's `.cruft.json` pins the exact template commit it was created from.
By default, `cruft update` pulls in whatever is on the template's `main` branch, which can
include half-finished work. Instead, point it at a tagged release so upgrades are deliberate:

```bash
cruft update --checkout v2.1.0
```

Check that release's `CHANGELOG.md` entry first to know what the update will actually change
before running it.

## Part B — changing the code

### Repository structure

```text
agent-deployment-template/
├── cookiecutter.json               ← variables collected from user at generation time
├── hooks/
│   ├── pre_gen_project.py          ← validates inputs before generation
│   └── post_gen_project.py         ← git init, uv sync, pre-commit install after generation
├── {{cookiecutter.project_slug}}/  ← TEMPLATE: becomes the new agent repo
│   └── ...
├── .github/workflows/              ← template repo CI
├── AGENTS.md                       ← this file (CLAUDE.md points here)
├── Makefile
└── instructions.md                 ← implementation plan and build progress
```

### Working on this template

#### Testing changes

Always validate before committing:

```bash
make validate
```

This runs `cookiecutter . --no-input`, enters the generated directory, installs dependencies, and runs unit tests and lint. If it fails, your change broke the template.

#### Adding a new cookiecutter variable

1. Add the variable to `cookiecutter.json`
2. Reference it in template files as `{{cookiecutter.your_variable}}`
3. Update the README.md variables table
4. Run `make validate` to confirm it renders correctly

#### Modifying the generated agent

Edit files inside `{{cookiecutter.project_slug}}/`. Remember these are templates — test changes with `make validate`, not by running the files directly.

#### Jinja2 / GitHub Actions conflict

GitHub Actions uses `${{ }}` syntax, which collides with Jinja2. Any `${{ }}`
expression inside `{{cookiecutter.project_slug}}/.github/workflows/` must be wrapped
in `{% raw %}...{% endraw %}`.

### Code conventions

- **Conventional commits** enforced by commitizen: `feat(scope): description`
- **Pre-commit hooks**: ruff (lint + format), pyright, detect-secrets, markdownlint
- Run `make pre-commit` before every commit; never use `--no-verify`
- Update `CHANGELOG.md` under `[Unreleased]` for every user-facing change
- No `print()` in Python package code — use `logging`

### Pre-commit (required)

```bash
make pre-commit
```

Fix ALL failures before committing. Never use `--no-verify`.

Ruff autofixes most lint issues: run `make format` then `make lint` to clear them.

### Conventional commits (required — enforced by commitizen hook)

```text
feat(template): add new cookiecutter variable for agent name
fix(hooks): correct slug validation regex
chore(ci): update ruff version
docs(readme): add architecture diagram
```

Types: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`

The commit-msg hook will reject non-conforming commits.

### CHANGELOG

Update `CHANGELOG.md` under `[Unreleased]` for every user-facing change before committing. Use Keep a Changelog format.

### Things that will bite you

- **Files under `{{cookiecutter.project_slug}}/` are templates, not runnable code.** Running
  them directly fails on unsubstituted Jinja. Test with `make validate`, never by executing
  them in place.
- **`${{ }}` in a generated workflow must be wrapped in `{% raw %}`.** Otherwise Jinja eats
  it at generation time and the workflow silently loses its expressions.
- **`make validate` generates with a relative path**, which is the one case where cruft
  cannot record a usable template reference. Generating from a URL or absolute path behaves
  differently — check both when touching `hooks/post_gen_project.py`.
- **`hooks/post_gen_project.py` also runs inside `cruft update`, twice.** Cruft renders the
  template at the old and the new commit and diffs the two copies. Anything the hook creates
  that is not template content (`.git`, `.venv`, `uv.lock` today) must be listed under
  `[tool.cruft] skip` in the generated `pyproject.toml`, or the update breaks.
- **The generated project's own pre-commit is a separate gate.** A change can pass this
  repo's checks and still leave generated projects failing theirs; `validate-template.yml`
  runs the generated set for exactly this reason.
- **Re-creating a generated project's engine changes the agent's identity.** The engine runs
  under its own Agent Identity, whose principal contains the engine ID. A template change that
  forces `infra/agent/` to replace the engine (a new `identity_type`, a changed `region`
  wiring) silently drops every grant to the old principal and is a MAJOR bump.
- **A cookiecutter variable rename is a MAJOR bump.** It breaks `cruft update` for every
  existing generated project.

### Definition of done

- [ ] `make validate` passes
- [ ] `make pre-commit` passes — never `--no-verify`
- [ ] Every affected cookiecutter variant still generates, lints and tests clean
- [ ] `CHANGELOG.md` updated under `[Unreleased]`, with the bump level considered
- [ ] README variables table updated if a variable was added or changed
