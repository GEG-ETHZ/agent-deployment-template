# Security Policy

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report vulnerabilities privately via [GitHub Security Advisories](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability):
Settings → Security → Advisories → Report a vulnerability

We aim to respond within 5 business days and to release a fix within 30 days for critical issues.

## Scope

Issues we consider in scope:

- **Prompt injection** — external content causing the agent to deviate from its instructions
- **PII leakage** — the agent repeating or storing user-provided personal data
- **System prompt exfiltration** — the agent revealing its system prompt verbatim
- **Credential exposure** — secrets committed to the repository or leaked in logs
- **Dependency CVEs** — HIGH or CRITICAL severity vulnerabilities in pinned dependencies

## Prompt security

Automated red-team tests run on every pull request via [promptfoo](https://promptfoo.dev). The test suite in `tests/evals/promptfoo.yaml` covers:

- Prompt injection attempts
- Jailbreak via roleplay and direct override
- System prompt exfiltration
- PII handling
- Harmful content refusal

To add a new test case, append to `tests/evals/promptfoo.yaml` and open a PR.

## Dependency scanning

Dependencies are audited automatically:

- `pip-audit` runs on every push to `main` and weekly on Monday
- `trufflehog` scans git history for secrets on every push to `main`
- CodeQL static analysis runs on every push to `main`

To acknowledge a false-positive CVE, add a comment `# audit-ignore: CVE-YYYY-XXXXX <reason>` on the relevant dependency line in `pyproject.toml`.

## Credential management

- Never commit `.env` files — they are gitignored
- Use `detect-secrets` (pre-commit hook) to prevent accidental credential commits
- In CI, secrets are stored as GitHub repository secrets and never printed to logs
- The deployed agent runs under its own Agent Identity, which holds only the roles granted in `infra/agent/`; it has no key to leak
- Local deploys use the deployer's own Application Default Credentials; no key file is involved
- CI deploys authenticate through Workload Identity Federation: each run's short-lived GitHub OIDC token is exchanged for GCP credentials, so no key is stored in GitHub. The repository holds only the grants in `infra/agent/ci.tf`; restrict who can deploy to `prod` with GitHub environment protection rules
