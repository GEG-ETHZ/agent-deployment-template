# Offline: the google provider is mocked, so nothing reaches GCP and no state is written.
# The mock stands in for what the API returns: the engine's id and the identity Vertex
# AI assigned it (spec.effectiveIdentity, as the dev engine reported it), and the
# existing Workload Identity pool the CI grants refer to.
mock_provider "google" {
  mock_resource "google_vertex_ai_reasoning_engine" {
    defaults = {
      id   = "projects/test-project/locations/europe-west1/reasoningEngines/42"
      name = "42"
      spec = {
        effective_identity = "agents.global.org-123456789012.system.id.goog/resources/aiplatform/projects/111111111111/locations/europe-west1/reasoningEngines/42"
      }
    }
  }

  mock_data "google_iam_workload_identity_pool" {
    defaults = {
      name = "projects/111111111111/locations/global/workloadIdentityPools/github-oidc"
    }
  }
}

variables {
  project_id     = "test-project"
  region         = "europe-west1"
  agent_slug     = "test-agent"
  staging_bucket = "test-staging"
  state_bucket   = "test-state"
  environment    = "dev"
}

run "engine_is_created_without_a_package" {
  command = plan

  # The API rejects a package_spec without the pickle, so the engine starts empty and
  # deploy.py ships the code, Python version included.
  assert {
    condition     = length(google_vertex_ai_reasoning_engine.agent.spec[0].package_spec) == 0
    error_message = "The engine must be created without a package_spec."
  }
}

run "engine_runs_under_its_own_agent_identity" {
  command = plan

  assert {
    condition     = google_vertex_ai_reasoning_engine.agent.spec[0].identity_type == "AGENT_IDENTITY"
    error_message = "The engine must use Agent Identity."
  }

  assert {
    condition     = google_vertex_ai_reasoning_engine.agent.spec[0].service_account == null
    error_message = "A service account cannot be combined with Agent Identity."
  }

  assert {
    condition     = google_vertex_ai_reasoning_engine.agent.display_name == "test-agent" && google_vertex_ai_reasoning_engine.agent.region == "europe-west1"
    error_message = "The engine is not named or placed as configured."
  }
}

run "grants_target_the_identity_the_engine_reports" {
  command = apply

  assert {
    condition     = output.agent_principal == "principal://agents.global.org-123456789012.system.id.goog/resources/aiplatform/projects/111111111111/locations/europe-west1/reasoningEngines/42"
    error_message = "agent_principal is not spec.effectiveIdentity with the principal:// scheme."
  }

  assert {
    condition     = alltrue([for m in google_project_iam_member.agent : m.member == output.agent_principal && m.project == "test-project"])
    error_message = "A grant targets something other than the agent's principal in the project."
  }
}

run "grants_trace_and_log_roles_only" {
  command = plan

  # Model calls come from the project-wide roles/aiplatform.agentDefaultAccess; the
  # broad roles/aiplatform.user is deliberately not granted.
  assert {
    condition     = toset(keys(google_project_iam_member.agent)) == toset(["roles/cloudtrace.agent", "roles/logging.logWriter"])
    error_message = "Default roles changed."
  }
}

run "outputs_the_engine_name_deploys_update" {
  command = apply

  assert {
    condition     = output.agent_resource_name == "projects/test-project/locations/europe-west1/reasoningEngines/42"
    error_message = "agent_resource_name is not the engine's resource name."
  }
}

run "no_ci_grants_without_a_github_repository" {
  command = plan

  assert {
    condition     = length(google_vertex_ai_reasoning_engine_iam_member.ci) + length(google_storage_bucket_iam_member.ci_staging) + length(google_storage_bucket_iam_member.ci_staging_bucket) + length(google_storage_bucket_iam_member.ci_state) + length(google_project_iam_member.ci_billing) == 0
    error_message = "CI grants exist although no GitHub repository is configured."
  }

  assert {
    condition     = output.ci_principal == null
    error_message = "ci_principal must be null without a GitHub repository."
  }

  assert {
    condition     = length(google_project_iam_custom_role.eval) + length(google_project_iam_member.eval_predict) + length(google_project_iam_member.eval_billing) == 0 && output.eval_principal == null
    error_message = "Eval grants exist although no GitHub repository is configured."
  }
}

# A grant on the repository alone would match a workflow on any branch, with or without an
# `environment:`, so the environment's required reviewers would not apply to it. The mapped
# attribute carries the environment, which GitHub only puts in a token once that
# environment's protection rules have passed.
run "ci_principal_is_one_repository_in_one_environment" {
  command = apply

  variables {
    github_repository = "example-org/test-repo"
  }

  assert {
    condition     = output.ci_principal == "principalSet://iam.googleapis.com/projects/111111111111/locations/global/workloadIdentityPools/github-oidc/attribute.repository_environment/example-org/test-repo:dev"
    error_message = "ci_principal is not the repository in the dev environment, in the github-oidc pool."
  }
}

run "prod_trusts_only_the_prod_environment" {
  command = apply

  variables {
    github_repository = "example-org/test-repo"
    environment       = "prod"
  }

  assert {
    condition     = endswith(output.ci_principal, "/attribute.repository_environment/example-org/test-repo:prod")
    error_message = "ci_principal must end in the prod environment."
  }

  assert {
    condition     = !strcontains(output.ci_principal, "attribute.repository/")
    error_message = "ci_principal must not be the repository-wide principal."
  }
}

run "environment_must_be_dev_or_prod" {
  command = plan

  variables {
    environment = "staging"
  }

  expect_failures = [var.environment]
}

run "ci_may_update_only_this_engine" {
  command = apply

  variables {
    github_repository = "example-org/test-repo"
  }

  assert {
    condition     = google_vertex_ai_reasoning_engine_iam_member.ci[0].reasoning_engine == "42" && google_vertex_ai_reasoning_engine_iam_member.ci[0].region == "europe-west1" && google_vertex_ai_reasoning_engine_iam_member.ci[0].role == "roles/aiplatform.user"
    error_message = "CI's Vertex AI role must sit on this engine only."
  }

  assert {
    condition     = google_vertex_ai_reasoning_engine_iam_member.ci[0].member == output.ci_principal
    error_message = "The engine grant targets something other than the CI principal."
  }
}

run "ci_reads_only_this_agents_state" {
  command = apply

  variables {
    github_repository = "example-org/test-repo"
  }

  assert {
    condition     = google_storage_bucket_iam_member.ci_state[0].bucket == "test-state" && google_storage_bucket_iam_member.ci_state[0].role == "roles/storage.objectViewer"
    error_message = "CI must read the state bucket, nothing more."
  }

  assert {
    condition     = strcontains(google_storage_bucket_iam_member.ci_state[0].condition[0].expression, "projects/_/buckets/test-state/objects/test-agent/")
    error_message = "CI's state access must be limited to this agent's prefix."
  }
}

run "ci_uploads_to_the_shared_staging_bucket_and_bills_the_project" {
  command = apply

  variables {
    github_repository = "example-org/test-repo"
  }

  assert {
    condition     = google_storage_bucket_iam_member.ci_staging[0].bucket == "test-staging" && google_storage_bucket_iam_member.ci_staging[0].role == "roles/storage.objectAdmin"
    error_message = "CI must be able to write the staging bucket."
  }

  # The SDK reads the bucket's metadata before uploading (storage.buckets.get), which
  # objectAdmin does not include.
  assert {
    condition     = google_storage_bucket_iam_member.ci_staging_bucket[0].bucket == "test-staging" && google_storage_bucket_iam_member.ci_staging_bucket[0].role == "roles/storage.bucketViewer"
    error_message = "CI must be able to read the staging bucket's metadata."
  }

  assert {
    condition     = google_project_iam_member.ci_billing[0].role == "roles/serviceusage.serviceUsageConsumer" && google_project_iam_member.ci_billing[0].member == output.ci_principal
    error_message = "CI must be allowed to bill its API calls to the project."
  }
}

run "ci_writes_only_to_this_agents_staging_folder" {
  command = apply

  variables {
    github_repository = "example-org/test-repo"
  }

  # The trailing slash keeps `test-agent` from also matching `test-agent-2/`.
  assert {
    condition     = google_storage_bucket_iam_member.ci_staging[0].condition[0].expression == "resource.name.startsWith(\"projects/_/buckets/test-staging/objects/test-agent/\")"
    error_message = "CI's staging access must be limited to this agent's folder."
  }

  # The SDK never lists the bucket, so the grant must not allow it: listing would show
  # every other agent's file names.
  assert {
    condition     = !strcontains(google_storage_bucket_iam_member.ci_staging[0].condition[0].expression, "storage.googleapis.com/Bucket")
    error_message = "CI's staging access must not allow listing the bucket."
  }
}

# The names below go into a CEL string, so a quote or a scheme must be refused.
run "agent_slug_with_a_quote_is_refused" {
  command = plan

  variables {
    agent_slug = "bad\"slug"
  }

  expect_failures = [var.agent_slug]
}

run "staging_bucket_with_a_scheme_is_refused" {
  command = plan

  variables {
    staging_bucket = "gs://test-staging"
  }

  expect_failures = [var.staging_bucket]
}

run "state_bucket_with_a_quote_is_refused" {
  command = plan

  variables {
    state_bucket = "bad\"bucket"
  }

  expect_failures = [var.state_bucket]
}

# The pull-request eval logs in as its own GitHub environment, `eval`: not prod, whose
# reviewers would block every pull request, and not the repository alone, which matches
# every workflow of every branch.
run "eval_principal_is_the_eval_environment" {
  command = apply

  variables {
    github_repository = "example-org/test-repo"
  }

  assert {
    condition     = output.eval_principal == "principalSet://iam.googleapis.com/projects/111111111111/locations/global/workloadIdentityPools/github-oidc/attribute.repository_environment/example-org/test-repo:eval"
    error_message = "eval_principal is not the repository in the eval environment, in the github-oidc pool."
  }

  assert {
    condition     = output.eval_principal != output.ci_principal
    error_message = "The eval must not share the deploy principal."
  }
}

# Any branch can run the eval, so it may call models and nothing else.
run "eval_may_only_call_models" {
  command = apply

  variables {
    github_repository = "example-org/test-repo"
  }

  assert {
    condition     = google_project_iam_custom_role.eval[0].permissions == toset(["aiplatform.endpoints.predict"]) && google_project_iam_custom_role.eval[0].project == "test-project"
    error_message = "The eval role must hold aiplatform.endpoints.predict only."
  }

  # Role IDs allow no hyphens.
  assert {
    condition     = google_project_iam_custom_role.eval[0].role_id == "agentEval_test_agent"
    error_message = "The eval role ID must be agentEval_ plus the slug with underscores."
  }

  assert {
    condition     = google_project_iam_member.eval_predict[0].role == google_project_iam_custom_role.eval[0].name && google_project_iam_member.eval_predict[0].member == output.eval_principal
    error_message = "The eval principal must hold the eval role."
  }

  assert {
    condition     = google_project_iam_member.eval_billing[0].role == "roles/serviceusage.serviceUsageConsumer" && google_project_iam_member.eval_billing[0].member == output.eval_principal
    error_message = "The eval must be allowed to bill its model calls to the project."
  }
}

run "eval_principal_has_no_rights_on_the_engine_or_the_buckets" {
  command = apply

  variables {
    github_repository = "example-org/test-repo"
  }

  assert {
    condition     = !contains([google_vertex_ai_reasoning_engine_iam_member.ci[0].member, google_storage_bucket_iam_member.ci_staging[0].member, google_storage_bucket_iam_member.ci_staging_bucket[0].member, google_storage_bucket_iam_member.ci_state[0].member], output.eval_principal)
    error_message = "The eval principal must hold nothing on the engine or the staging and state buckets."
  }
}

# The dev and prod states are applied separately; only one may own the eval role.
run "prod_state_grants_the_eval_nothing_by_default" {
  command = plan

  variables {
    github_repository = "example-org/test-repo"
    environment       = "prod"
  }

  assert {
    condition     = length(google_project_iam_custom_role.eval) + length(google_project_iam_member.eval_predict) + length(google_project_iam_member.eval_billing) == 0
    error_message = "The prod state must not grant the eval while eval_state_env is dev."
  }
}

run "eval_can_move_to_the_prod_state" {
  command = apply

  variables {
    github_repository = "example-org/test-repo"
    environment       = "prod"
    eval_state_env    = "prod"
  }

  assert {
    condition     = length(google_project_iam_member.eval_predict) == 1 && endswith(output.eval_principal, ":eval")
    error_message = "With eval_state_env = prod, the prod state must grant the eval."
  }
}

run "eval_state_env_must_be_dev_or_prod" {
  command = plan

  variables {
    eval_state_env = "staging"
  }

  expect_failures = [var.eval_state_env]
}
