# What GitHub Actions (deploy.yml) may do to ship this agent's code, and nothing more.
#
# CI logs in through Workload Identity Federation, with no service account and no key:
# GitHub's OIDC token for a run of `github_repository` is exchanged in the existing pool
# for a short-lived token, and the APIs see the repository itself as the caller. Every
# grant below names that one repository, so other repositories in the pool get nothing.
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
  ci_principal = local.ci_enabled ? "principalSet://iam.googleapis.com/${data.google_iam_workload_identity_pool.github[0].name}/attribute.repository/${var.github_repository}" : null
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

# Upload the pickle, requirements and dependencies. The staging bucket is shared, and this
# grant covers the whole bucket: CI can overwrite other agents' staging files too. Accepted,
# not overlooked. The bucket must use uniform bucket-level access: Cloud Storage rejects a
# federated principal's writes to a bucket with fine-grained ACLs (412 on upload).
resource "google_storage_bucket_iam_member" "ci_staging" {
  count = local.ci_enabled ? 1 : 0

  bucket = var.staging_bucket
  role   = "roles/storage.objectAdmin"
  member = local.ci_principal
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
