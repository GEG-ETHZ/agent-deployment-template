# The deployed agent's engine, its Agent Identity, and the roles that identity holds.
#
# OpenTofu creates the engine first, with no code: that is enough for Vertex AI to give
# it its own resource-scoped principal (spec.effective_identity), so the grants below
# exist before any code runs. `deploy.py` then ships the code to this engine with the
# SDK, and never creates one. Beyond the project's Google-managed agent default access
# (see variables.tf), everything the agent may do is granted here.

resource "google_vertex_ai_reasoning_engine" "agent" {
  display_name = var.agent_slug
  region       = var.region

  spec {
    identity_type = "AGENT_IDENTITY"
  }

  lifecycle {
    # deploy.py owns the code: the pickled agent, its requirements, the container's
    # Python and environment, and the methods it exposes. Without this, every apply
    # would strip what the last deploy shipped. The Python version cannot be set here:
    # the API rejects a package_spec without the pickle (see deployment/python_version.py).
    ignore_changes = [
      spec[0].agent_framework,
      spec[0].class_methods,
      spec[0].deployment_spec,
      spec[0].package_spec,
    ]
  }
}

locals {
  # The identity Vertex AI assigned the engine, with the scheme IAM expects.
  agent_principal = "principal://${google_vertex_ai_reasoning_engine.agent.spec[0].effective_identity}"
}

# _member, never _binding or _policy: those own the role's whole member list or the
# project's whole policy, and would strip every grant this agent does not know about.
resource "google_project_iam_member" "agent" {
  for_each = var.roles

  project = var.project_id
  role    = each.value
  member  = local.agent_principal
}
