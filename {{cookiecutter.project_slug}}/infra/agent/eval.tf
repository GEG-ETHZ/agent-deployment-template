# What the pull-request eval (eval.yml) may do: call Gemini, and nothing more.
#
# The eval runs the agent in the GitHub runner and grades its answers with a second model,
# so it needs model calls on the project, which ci.tf's deploy grants do not give. It logs
# in like deploy.yml, through Workload Identity Federation, but as its own GitHub
# environment, `eval`:
#
# - Not as `prod` or `dev`: every pull request runs the eval, and those environments'
#   reviewers and branch rules would block it, or would have to be weakened for it.
# - Not as the repository alone: that principal matches every workflow of every branch.
#   Naming the `eval` environment keeps the grant to jobs that declare it.
#
# Any branch can run the eval job, so the grant is as narrow as a model call allows: a
# custom role with aiplatform.endpoints.predict, which covers generateContent on publisher
# models. roles/aiplatform.user would also let a pull request create or delete any Vertex
# resource of the project, other agents' engines included. The eval principal gets nothing
# on the engine or on the staging and state buckets.
#
# Only one state grants it: the dev and prod states are applied separately, and a custom
# role owned by both would be created by one and deleted by the other. The eval bills the
# project of that environment (dev by default).

locals {
  eval_enabled = local.ci_enabled && var.environment == var.eval_state_env

  eval_principal = local.eval_enabled ? "principalSet://iam.googleapis.com/${data.google_iam_workload_identity_pool.github[0].name}/attribute.repository_environment/${var.github_repository}:eval" : null

  # Role IDs allow letters, digits, `_` and `.`, up to 64 characters; agent_slug may hold
  # hyphens. One role per agent, so two agents in a project never share an owner.
  eval_role_id = substr("agentEval_${replace(var.agent_slug, "-", "_")}", 0, 64)
}

resource "google_project_iam_custom_role" "eval" {
  count = local.eval_enabled ? 1 : 0

  project     = var.project_id
  role_id     = local.eval_role_id
  title       = "Eval model calls: ${var.agent_slug}"
  description = "Lets the GitHub eval of ${var.agent_slug} call Vertex AI models. Managed in infra/agent/eval.tf."
  permissions = ["aiplatform.endpoints.predict"]
}

resource "google_project_iam_member" "eval_predict" {
  count = local.eval_enabled ? 1 : 0

  project = var.project_id
  role    = google_project_iam_custom_role.eval[0].name
  member  = local.eval_principal
}

# A federated identity belongs to no project; this lets the eval's model calls be billed
# to this one. It grants no access to any data.
resource "google_project_iam_member" "eval_billing" {
  count = local.eval_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = local.eval_principal
}
