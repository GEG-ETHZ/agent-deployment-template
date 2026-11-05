---
description: Deploy the agent to Vertex AI Agent Engine (prod)
---

Run `make deploy-prod`. After it completes:

1. Report the Agent Engine resource name from `tofu -chdir=infra/agent output -raw agent_resource_name` or stdout
2. If the deploy fails, read the error output carefully and suggest a specific fix
3. Common failures:
   - `GOOGLE_CLOUD_PROJECT not set` → user needs to fill in `.env`
   - `GCS_STAGING_BUCKET not set` → run `make setup-gcp` first
   - Authentication error → run `gcloud auth application-default login`
   - `tofu: command not found` → install OpenTofu 1.8+
   - `bucket doesn't exist` at `tofu init` → run `make setup-gcp` first (creates the state bucket)
   - Health check fails with `PermissionDenied` → the agent identity's grants have not
     propagated or were not applied; run `make infra-apply ENV=prod`, then the health check
   - `AGENT_ENGINE_RESOURCE_NAME is not set` → `deploy.py` was run by hand; use `make deploy-prod`
   - The plan wants to create an engine although one exists → it was created outside
     OpenTofu; adopt it with `make infra-import ENV=prod ENGINE=<name>` instead of applying
