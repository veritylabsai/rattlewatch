#!/usr/bin/env bash
# Rebuild the Verity image (which re-ingests the live CPSC feed at build time)
# and redeploy both Cloud Run services.
#
# Runs inside a Cloud Run Job on a schedule, so the data stays current without
# anyone touching it.

set -euo pipefail

PROJECT="${PROJECT:-verity-labs}"
REGION="${REGION:-us-central1}"
REPO="${REPO:-veritylabsai/verity}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/verity/verity:latest"

echo "[refresh] $(date -u +%Y-%m-%dT%H:%M:%SZ) starting"
echo "[refresh] fetching source for ${REPO}"

curl -sSL "https://github.com/${REPO}/archive/refs/heads/main.tar.gz" -o /tmp/src.tgz
mkdir -p /src
tar -xzf /tmp/src.tgz -C /src --strip-components=1
cd /src

echo "[refresh] building ${IMAGE}"
# --suppress-logs: the job's service account can write logs but cannot stream
# them, and gcloud treats a streaming failure as a build failure.
gcloud builds submit --tag "${IMAGE}" --project "${PROJECT}" --suppress-logs --quiet

echo "[refresh] deploying verity-api"
gcloud run deploy verity-api \
  --image "${IMAGE}" --region "${REGION}" \
  --allow-unauthenticated --port 8000 --memory 512Mi --cpu 1 \
  --max-instances 3 --min-instances 0 \
  --project "${PROJECT}" --quiet

echo "[refresh] deploying verity-mcp"
gcloud run deploy verity-mcp \
  --image "${IMAGE}" --region "${REGION}" \
  --allow-unauthenticated --port 8000 --memory 512Mi --cpu 1 \
  --max-instances 1 --min-instances 0 \
  --command python --args "-m,verity,mcp,--http,--host,0.0.0.0,--port,8000" \
  --project "${PROJECT}" --quiet

echo "[refresh] done $(date -u +%Y-%m-%dT%H:%M:%SZ)"
