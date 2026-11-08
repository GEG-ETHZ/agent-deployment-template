---
description: Deploy the agent to Vertex AI Agent Engine (prod)
---

Never run `make infra-apply`, `make deploy-prod`, `tofu apply` or `tofu destroy`.
Never pass `-auto-approve`.

An apply changes the production project's IAM grants (the agent's roles and CI's access),
and its confirmation prompt is the review: a person reads the plan and confirms it.

1. Ask the person to run `make infra-apply ENV=prod` in their own shell, read the plan and
   confirm it. Wait until they say it is done.
2. Run `make deploy-code ENV=prod`. It reads the engine from the OpenTofu state, ships the
   code and runs the health check. It never applies.
3. Report the Agent Engine resource name from
   `tofu -chdir=infra/agent output -raw agent_resource_name`
4. If the deploy fails, read the error output carefully and suggest a specific fix
5. Common failures:
   - `GOOGLE_CLOUD_PROJECT not set` → user needs to fill in `.env`
   - Authentication error → run `gcloud auth application-default login`
   - `tofu: command not found` → install OpenTofu 1.8+
   - `bucket doesn't exist` at `tofu init`, or `make setup-gcp` reports a missing bucket → the
     shared staging and state buckets are managed in the `geg-core-infra` repository; they
     must be applied there first
   - Health check fails with `PermissionDenied` → the agent identity's grants have not
     propagated or were not applied; ask the person to run `make infra-apply ENV=prod`, then
     run `make health-check`
   - `AGENT_ENGINE_RESOURCE_NAME is not set` → `deploy.py` was run by hand; use
     `make deploy-code ENV=prod`
   - The person's plan wants to create an engine although one exists → it was created outside
     OpenTofu; ask them to adopt it with `make infra-import ENV=prod ENGINE=<name>` instead of
     applying
