terraform {
  required_version = ">= 1.8"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.9"
    }
  }

  # State lives in the bucket shared by every agent of the project, one prefix per agent
  # and environment; both are passed at init (see `make infra-init`):
  #   tofu init -backend-config="bucket=<state bucket>" -backend-config="prefix=<agent>/<env>"
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
}
