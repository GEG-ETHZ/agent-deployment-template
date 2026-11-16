#!/usr/bin/env bash
# One-time GCP project bootstrap for {{cookiecutter.project_name}}.
#
# Run once per GCP project — once for dev, once for prod, each pointed at its
# own GOOGLE_CLOUD_PROJECT. Safe to re-run.
#
# Creates no bucket, no service account and no key. The staging and state buckets are shared
# by every agent of the project and are managed in the geg-core-infra repository (module
# agent-buckets), so this script only checks that they exist. The deployed agent runs under
# its own Agent Identity: OpenTofu (infra/agent) creates the engine and grants that identity
# its roles (see "Runtime identity" in AGENTS.md). Deploys run from your own gcloud login
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

echo "=== GCP Bootstrap: {{cookiecutter.project_name}} ($GH_ENVIRONMENT) ==="
echo "  Project:       $PROJECT"
echo "  Location:      $LOCATION"
echo "  Staging:       gs://$BUCKET"
echo "  Tofu state:    gs://$STATE_BUCKET"
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

# Both buckets are shared by every agent of the project and managed in geg-core-infra, which
# gives them their access settings. Written by whoever deploys and by CI, the staging bucket
# is read by Vertex AI's own service agent when it builds the agent. Report every missing one
# at once, and stop: no deploy works without them.
echo "> Checking the shared buckets..."
MISSING=0
for shared_bucket in "$BUCKET" "$STATE_BUCKET"; do
  if gcloud storage buckets describe "gs://$shared_bucket" --project="$PROJECT" &>/dev/null; then
    echo "  gs://$shared_bucket exists."
  else
    echo "  missing: gs://$shared_bucket"
    MISSING=1
  fi
done
if [ "$MISSING" -ne 0 ]; then
  echo "" >&2
  echo "ERROR: a shared bucket does not exist in $PROJECT." >&2
  echo "  Both are managed in the geg-core-infra repository (module agent-buckets," >&2
  echo "  environments/<env>/storage.tf), not created here. Apply it there first." >&2
  exit 1
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
# The pull-request eval (eval.yml) logs in as its own environment, `eval`, granted model
# calls by one state only (infra/agent/eval.tf): dev's by default, prod's for a project
# without dev. Printed for both, so a prod-only project learns about it too.
echo "The pull-request eval (eval.yml) logs in as a GitHub environment named 'eval'."
echo "Create it with NO required reviewers and NO deployment-branch rule (pull requests"
echo "run from feature branches), and give it the same three variables as above."
if [ "$GH_ENVIRONMENT" = "dev" ]; then
  echo "'make infra-apply ENV=dev' grants it model calls in $PROJECT, and nothing else."
else
  echo "Dev's apply grants it, so skip this if you have a dev environment. Without one,"
  echo "set EVAL_STATE_ENV=prod in .env, then 'make infra-apply ENV=prod' grants it model"
  echo "calls in $PROJECT, and nothing else."
fi
echo "Applying it creates a custom role: that needs roles/iam.roleAdmin (or owner)."
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
