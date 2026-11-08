#!/usr/bin/env bash
# One-time GCP project bootstrap for {{cookiecutter.project_name}}.
#
# Run once per GCP project — once for dev, once for prod, each pointed at its
# own GOOGLE_CLOUD_PROJECT. Safe to re-run — checks before creating.
#
# Creates no service account and no key: the deployed agent runs under its own
# Agent Identity. OpenTofu (infra/agent) creates the engine and grants that identity its
# roles (see "Runtime identity" in AGENTS.md). Deploys run from your own gcloud login
# (`gcloud auth application-default login`).
#
# Usage:
#   ./deployment/scripts/setup_gcp.sh dev     # bootstrap the dev project
#   ./deployment/scripts/setup_gcp.sh prod    # bootstrap the prod project (default)
set -euo pipefail

GH_ENVIRONMENT="${1:-prod}"
case "$GH_ENVIRONMENT" in
  dev|prod) ;;
  *)
    echo "Usage: $0 [dev|prod]  (defaults to prod)" >&2
    exit 1
    ;;
esac

PROJECT="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT in .env or export it first}"
LOCATION="${GOOGLE_CLOUD_LOCATION:-europe-west1}"
BUCKET="${GCS_STAGING_BUCKET:-${PROJECT}-agent-staging}"
BUCKET="${BUCKET#gs://}"

# OpenTofu state for every agent of the project, one prefix per agent and environment.
# Keep in step with STATE_BUCKET in the Makefile.
STATE_BUCKET="${STATE_BUCKET:-${PROJECT}-agents-state}"
STATE_LOCATION="${STATE_LOCATION:-$LOCATION}"

echo "=== GCP Bootstrap: {{cookiecutter.project_name}} ($GH_ENVIRONMENT) ==="
echo "  Project:       $PROJECT"
echo "  Location:      $LOCATION"
echo "  Staging:       gs://$BUCKET"
echo "  Tofu state:    gs://$STATE_BUCKET ($STATE_LOCATION)"
echo ""

# Enable required APIs
echo "> Enabling APIs..."
gcloud services enable \
  aiplatform.googleapis.com \
  logging.googleapis.com \
  cloudtrace.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  --project="$PROJECT"

# Create GCS staging bucket (idempotent). Written by whoever deploys, read by Vertex AI's
# own service agent when it builds the agent; the agent identity is granted nothing here.
echo "> Creating staging bucket..."
if ! gcloud storage buckets describe "gs://$BUCKET" --project="$PROJECT" &>/dev/null; then
  gcloud storage buckets create "gs://$BUCKET" \
    --project="$PROJECT" \
    --location="$LOCATION" \
    --uniform-bucket-level-access \
    --public-access-prevention
else
  echo "  Bucket already exists, skipping."
fi

# Create the shared OpenTofu state bucket (idempotent). Versioned, so a bad apply's state
# can be recovered; it holds the project's IAM layout, so it is never public.
echo "> Creating OpenTofu state bucket..."
if ! gcloud storage buckets describe "gs://$STATE_BUCKET" --project="$PROJECT" &>/dev/null; then
  gcloud storage buckets create "gs://$STATE_BUCKET" \
    --project="$PROJECT" \
    --location="$STATE_LOCATION" \
    --uniform-bucket-level-access \
    --public-access-prevention
  gcloud storage buckets update "gs://$STATE_BUCKET" \
    --project="$PROJECT" \
    --versioning
else
  echo "  Bucket already exists, skipping."
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Deploy from your machine, logged in with your own account:"
echo ""
echo "  gcloud auth application-default login"
echo "  make deploy-$GH_ENVIRONMENT"
echo ""
echo "That applies infra/agent (creates the engine and its Agent Identity, grants its"
echo "roles; asks to confirm the plan), ships the code to that engine, and health-checks it."
echo "The engine's name lives in the OpenTofu state, not in .env."
echo ""
# CI's grants (infra/agent/ci.tf) look this pool up in the project, so `make infra-apply`
# fails on it while CI is switched on and the pool is missing. The pool is managed in
# geg-core-infra (module github-oidc-pool), not here, so only warn.
WIF_POOL="${WIF_POOL_ID:-github-oidc}"
if ! gcloud iam workload-identity-pools describe "$WIF_POOL" \
  --location=global --project="$PROJECT" &>/dev/null; then
  echo "WARNING: Workload Identity pool '$WIF_POOL' does not exist in $PROJECT."
  echo "  It is managed in the geg-core-infra repository (module github-oidc-pool)."
  echo "  Until it exists, 'make infra-apply' fails on the pool lookup. To deploy without CI,"
  echo "  run: make deploy-$GH_ENVIRONMENT GITHUB_REPOSITORY="
  echo ""
fi
echo "CI deploys (deploy.yml) log in through Workload Identity Federation, with no key."
echo "Add these as '$GH_ENVIRONMENT' environment variables in GitHub:"
echo "  GOOGLE_CLOUD_PROJECT           = $PROJECT"
echo "  GOOGLE_CLOUD_LOCATION          = $LOCATION"
echo "  GCP_WORKLOAD_IDENTITY_PROVIDER = projects/$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')/locations/global/workloadIdentityPools/github-oidc/providers/github"
echo "Then run 'make infra-apply ENV=$GH_ENVIRONMENT' to grant the repository its access."
echo ""
echo "Update your .env file with:"
cat <<ENV
GOOGLE_CLOUD_PROJECT=$PROJECT
GOOGLE_CLOUD_LOCATION=$LOCATION
MODEL_PROVIDER=google
ENV
echo ""
echo "(The staging bucket is derived from the project id; add GCS_STAGING_BUCKET only"
echo " to override it.)"
