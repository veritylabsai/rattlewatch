#!/usr/bin/env bash
# Rebuild the Rattlewatch image (which re-ingests the live CPSC feed at build time)
# and redeploy both Cloud Run services.
#
# Runs inside a Cloud Run Job on a schedule, so the data stays current without
# anyone touching it.

set -euo pipefail

PROJECT="${PROJECT:-verity-labs}"
REGION="${REGION:-us-central1}"
REPO="${REPO:-veritylabsai/rattlewatch}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/rattlewatch/rattlewatch:latest"

echo "[refresh] $(date -u +%Y-%m-%dT%H:%M:%SZ) starting"
echo "[refresh] fetching source for ${REPO}"

curl -sSL "https://github.com/${REPO}/archive/refs/heads/main.tar.gz" -o /tmp/src.tgz
mkdir -p /src
tar -xzf /tmp/src.tgz -C /src --strip-components=1
cd /src

echo "[refresh] building ${IMAGE}"
#
# IMPORTANT: `gcloud builds submit` exits non-zero for a service account that is
# not a project Viewer/Owner, because it cannot stream build logs -- even though
# the BUILD ITSELF SUCCEEDS and the image is pushed. Under `set -e` that would
# abort the refresh before the deploy steps (which is exactly what happened).
# So tolerate the exit code, then verify the build independently instead of
# trusting the CLI.
set +e
gcloud builds submit --tag "${IMAGE}" --project "${PROJECT}" --suppress-logs --quiet
submit_rc=$?
set -e

if [ "${submit_rc}" -ne 0 ]; then
  echo "[refresh] submit returned ${submit_rc}; verifying build status independently"
  latest_status=$(gcloud builds list --project "${PROJECT}" --limit=1 --format="value(status)")
  echo "[refresh] most recent build status: ${latest_status}"
  if [ "${latest_status}" != "SUCCESS" ]; then
    echo "[refresh] build did NOT succeed; aborting"
    exit 1
  fi
  echo "[refresh] build succeeded despite the CLI exit code; continuing"
fi

echo "[refresh] deploying verity-api"
gcloud run deploy verity-api \
  --image "${IMAGE}" --region "${REGION}" \
  --allow-unauthenticated --port 8000 --memory 512Mi --cpu 1 \
  --max-instances 3 --min-instances 0 \
  --project "${PROJECT}" --quiet

echo "[refresh] deploying verity-mcp"
# NOTE: use `--flag=value` here, not `--flag value`. The --args value begins with
# "-", so the space-separated form is parsed as another flag and gcloud prints
# its help instead of deploying (exit 2).
gcloud run deploy verity-mcp \
  --image="${IMAGE}" --region="${REGION}" \
  --allow-unauthenticated --port=8000 --memory=512Mi --cpu=1 \
  --max-instances=1 --min-instances=0 \
  --command=python --args="-m,rattlewatch,mcp,--http,--host,0.0.0.0,--port,8000" \
  --project="${PROJECT}" --quiet

echo "[refresh] done $(date -u +%Y-%m-%dT%H:%M:%SZ)"
