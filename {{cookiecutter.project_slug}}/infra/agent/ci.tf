# What GitHub Actions (deploy.yml) may do to ship this agent's code, and nothing more.
#
# CI logs in through Workload Identity Federation, with no service account and no key:
# GitHub's OIDC token for a run of `github_repository` is exchanged in the existing pool
# for a short-lived token, and the APIs see the repository itself as the caller. Every
# grant below names that one repository in one environment, so other repositories in the
# pool, and this repository's other environments, get nothing.
#
# The environment is part of the principal on purpose. A grant on the repository alone
# matches a workflow on any branch, with or without an `environment:`, so the
# environment's required reviewers and branch rules would not apply to it. GitHub only puts
# `environment:<name>` in a token after those rules have passed, so this grant is gated by
# them. This is what makes a protection rule on the `prod` environment mean something.
#
# The pool and its provider are referenced, never managed here: they are shared by every
# repository of the organisation, and two states owning them would fight over them.
#
# CI only reads the OpenTofu state and ships code. It never applies, so it holds no IAM
# rights: changing the engine or any grant stays a local `make infra-apply`.

locals {
  ci_enabled = var.github_repository != ""
}

data "google_iam_workload_identity_pool" "github" {
  count = local.ci_enabled ? 1 : 0

  workload_identity_pool_id = var.wif_pool_id
}

locals {
  ci_principal = local.ci_enabled ? "principalSet://iam.googleapis.com/${data.google_iam_workload_identity_pool.github[0].name}/attribute.repository_environment/${var.github_repository}:${var.environment}" : null
}

# Update and query this engine only: not the project, where it could reach every agent.
resource "google_vertex_ai_reasoning_engine_iam_member" "ci" {
  count = local.ci_enabled ? 1 : 0

  project          = var.project_id
  region           = var.region
  reasoning_engine = google_vertex_ai_reasoning_engine.agent.name
  role             = "roles/aiplatform.user"
  member           = local.ci_principal
}

# Upload the pickle, requirements and dependencies. The staging bucket is shared by every
# agent of the project, so the grant is limited to this agent's folder: the SDK writes only
# under `<agent_slug>/` (deploy.py's gcs_dir_name), and a pickle that CI could replace in
# another agent's folder would run under that agent's identity.
#
# The condition has no clause for the bucket itself. The SDK never lists objects, and
# listing would reveal every other agent's file names; reading the bucket's metadata
# (storage.buckets.get) is the separate ci_staging_bucket grant below. The trailing slash
# keeps `my-agent` from also matching `my-agent-2/`.
#
# Conditions on a bucket need uniform bucket-level access, which CI needs anyway: Cloud
# Storage rejects a federated principal's writes to a bucket with fine-grained ACLs (412).
resource "google_storage_bucket_iam_member" "ci_staging" {
  count = local.ci_enabled ? 1 : 0

  bucket = var.staging_bucket
  role   = "roles/storage.objectAdmin"
  member = local.ci_principal

  condition {
    title       = "${var.agent_slug}-staging-only"
    description = "Objects under ${var.agent_slug}/ only."
    expression  = "resource.name.startsWith(\"projects/_/buckets/${var.staging_bucket}/objects/${var.agent_slug}/\")"
  }
}

# The SDK reads the staging bucket's metadata before uploading (storage.buckets.get),
# which objectAdmin does not include. bucketViewer adds only that, on this one bucket.
resource "google_storage_bucket_iam_member" "ci_staging_bucket" {
  count = local.ci_enabled ? 1 : 0

  bucket = var.staging_bucket
  role   = "roles/storage.bucketViewer"
  member = local.ci_principal
}

# Read this agent's state to learn the engine name. Listing is checked against the
# bucket, not an object, so the condition lets it list the bucket (other agents' state
# object names are visible) but read only objects under this agent's prefix.
resource "google_storage_bucket_iam_member" "ci_state" {
  count = local.ci_enabled ? 1 : 0

  bucket = var.state_bucket
  role   = "roles/storage.objectViewer"
  member = local.ci_principal

  condition {
    title       = "${var.agent_slug}-state-only"
    description = "Objects under ${var.agent_slug}/, plus listing the bucket."
    expression  = "resource.name.startsWith(\"projects/_/buckets/${var.state_bucket}/objects/${var.agent_slug}/\") || resource.type == \"storage.googleapis.com/Bucket\""
  }
}

# A federated identity belongs to no project; this lets its API calls be billed to this
# one. It grants no access to any data.
resource "google_project_iam_member" "ci_billing" {
  count = local.ci_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = local.ci_principal
}
