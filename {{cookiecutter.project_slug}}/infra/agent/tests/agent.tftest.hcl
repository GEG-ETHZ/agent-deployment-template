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
      name = "projects/111111111111/locations/global/workloadIdentityPools/github-actions"
    }
  }
}

variables {
  project_id     = "test-project"
  region         = "europe-west1"
  agent_slug     = "test-agent"
  staging_bucket = "test-staging"
  state_bucket   = "test-state"
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
}

run "ci_principal_is_the_repository_in_the_existing_pool" {
  command = apply

  variables {
    github_repository = "example-org/test-repo"
  }

  assert {
    condition     = output.ci_principal == "principalSet://iam.googleapis.com/projects/111111111111/locations/global/workloadIdentityPools/github-actions/attribute.repository/example-org/test-repo"
    error_message = "ci_principal is not the repository's principalSet in the pool."
  }
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
