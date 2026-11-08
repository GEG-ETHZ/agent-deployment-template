variable "project_id" {
  description = "The GCP project the agent runs in and whose roles it is granted."
  type        = string
}

variable "region" {
  description = "Vertex AI region of the agent, e.g. europe-west1. Changing it re-creates the engine, and with it the agent's identity."
  type        = string
}

variable "agent_slug" {
  description = "The agent's name: the engine's display name, and its folder in the state and staging buckets. The Makefile passes AGENT_SLUG."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9_-]*$", var.agent_slug))
    error_message = "agent_slug may hold only lowercase letters, digits, hyphens and underscores: it is written into IAM conditions and bucket paths."
  }
}

variable "staging_bucket" {
  description = "Bucket deploy.py uploads the agent's code to, without gs://."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9._-]*[a-z0-9]$", var.staging_bucket))
    error_message = "staging_bucket must be a bare bucket name, without gs://."
  }
}

variable "state_bucket" {
  description = "Bucket holding the OpenTofu state of every agent of the project."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9._-]*[a-z0-9]$", var.state_bucket))
    error_message = "state_bucket must be a bare bucket name, without gs://."
  }
}

variable "github_repository" {
  description = "owner/name of the GitHub repository whose deploy.yml may ship this agent's code, e.g. example-org/my-agent. Empty grants CI nothing."
  type        = string
  default     = ""
}

variable "wif_pool_id" {
  description = "Existing Workload Identity pool that trusts GitHub Actions tokens. Referenced, never managed here."
  type        = string
  default     = "github-actions"
}

# Every Agent Engine agent identity in the project also holds roles/aiplatform.agentDefaultAccess
# (ALPHA): Google grants it to the project's whole agent principalSet when the first agent with
# Agent Identity is created. It covers model calls, so roles/aiplatform.user -- which can also
# create and delete Vertex resources -- is not granted. Traces and logs are granted here as well,
# so the agent keeps them even if that default binding is removed.
variable "roles" {
  description = "Project roles the agent identity holds on top of the project's agent default access."
  type        = set(string)
  default = [
    "roles/cloudtrace.agent",  # export spans (agent/observability.py)
    "roles/logging.logWriter", # write log entries
  ]
}
