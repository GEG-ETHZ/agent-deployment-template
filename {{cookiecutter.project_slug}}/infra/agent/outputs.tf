output "agent_resource_name" {
  description = "The engine `make deploy-*` ships code to, as AGENT_ENGINE_RESOURCE_NAME."
  value       = google_vertex_ai_reasoning_engine.agent.id
}

output "ci_principal" {
  description = "The WIF principal deploy.yml runs as: the GitHub repository in one environment; null without github_repository."
  value       = local.ci_principal
}

output "agent_principal" {
  description = "IAM principal of the deployed agent; grant it any further access here."
  value       = local.agent_principal
}
