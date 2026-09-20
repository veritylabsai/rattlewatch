# Deployment & promotion runbook

This is the mechanical path from working code (already built and tested) to a
live, discoverable service. It is written so the ~30 minutes of human setup is
click-by-click, not exploratory.

## What gets deployed

Two small services, both from this one repo:

| Service | Command | Port | Purpose |
|---|---|---|---|
| **REST API** | `python -m verity serve` | 8000 | The hosted product: `/v1/*`, `/docs`, x402 premium |
| **MCP server** | `python -m verity mcp --http` | 8001 | MCP-over-HTTP for agents (optional; REST API is primary) |

The REST API is the primary monetization surface — it is HTTP-native, which is
exactly what the x402 `402 Payment Required` flow expects. MCP is a thin adapter
over the same engine; locally, agents connect to it over stdio.

## Accounts you create (one-time, ~30 min)

1. **GitHub** — hosts the repo (this is the primary *discovery* surface; agents
   and developers find MCP servers on GitHub).
2. **One host**, either:
   - **Google Cloud** (use your existing credits), or
   - **Render** (free tier; service sleeps when idle and wakes on request).

## Option A — Google Cloud Run (uses your credits)

```bash
# one-time setup
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# build & deploy the API
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/verity
gcloud run deploy verity-api \
  --image gcr.io/YOUR_PROJECT_ID/verity \
  --region us-central1 --allow-unauthenticated --memory 1Gi

# (optional) deploy MCP-over-HTTP as a second service
gcloud run deploy verity-mcp \
  --image gcr.io/YOUR_PROJECT_ID/verity \
  --region us-central1 --allow-unauthenticated --memory 1Gi \
  --command "python" --args "-m verity mcp --http --host 0.0.0.0 --port 8001"
```

Note: `gcloud run deploy` for the MCP service needs a `--container-port 8001` flag
when the image's CMD is overridden to a non-default port.

## Option B — Render (free tier)

1. `render.com` → New → **Web Service** → connect the GitHub repo.
2. Runtime: **Docker**. (The `Dockerfile` is already in the repo.)
3. Start command: `python -m verity serve --host 0.0.0.0 --port $PORT`.
4. Deploy. Note the free tier sleeps after ~15 min idle and cold-starts on the
   next request — acceptable for an API that agents call on demand.

## Promotion status

> 🚧 **The critical path is ONE web action: submit Verity to Glama.**
> Both `awesome-mcp-servers` (95k★) and `awesome-remote-mcp-servers` require a
> Glama score badge on every entry, so both PRs are blocked behind a Glama
> listing. Glama has no public submission API — it needs the web form at
> <https://glama.ai/mcp/servers> (and for a hosted server, also
> <https://glama.ai/mcp/connectors>). Nothing else on this page is blocked.

| Channel | Status |
|---|---|
| **Official MCP Registry** | ✅ live — `io.github.veritylabsai/verity` v0.1.0 |
| GitHub topics + tagged release | ✅ done (12 discovery topics) |
| `awesome-mcp-servers` (95k★) | ⏳ PR [#14759](https://github.com/punkpeye/awesome-mcp-servers/pull/14759) open, mergeable — **blocked on the Glama badge** |
| `awesome-remote-mcp-servers` | ⏳ same Glama requirement |
| **Glama** | ❌ not listed — needs <https://glama.ai/mcp/servers> |
| **Smithery** | ❌ not listed — needs <https://smithery.ai/new> (paste the endpoint URL) |
| PulseMCP / mcp.so | auto-sync from the official registry; not present yet |

Once Glama lists the connector, add the badge line to the PR description and the
entry becomes mergeable:

```
[![veritylabsai/verity MCP server](https://glama.ai/mcp/servers/veritylabsai/verity/badges/score.svg)](https://glama.ai/mcp/servers/veritylabsai/verity)
```

**Everything else is automated**: the daily refresh, the CI gate, and the
freshness health check all run without intervention.


## Ongoing operations (now automated)

**Data refresh is scheduled and working.** A Cloud Run Job (`verity-refresh`)
rebuilds the image — which re-ingests the live CPSC feed at build time — and
redeploys both services. Cloud Scheduler triggers it **daily at 06:00 UTC**.

```bash
# check history
gcloud run jobs executions list --job=verity-refresh --region=us-central1 --project=verity-labs

# run it by hand if you want fresh data immediately
gcloud run jobs execute verity-refresh --region=us-central1 --project=verity-labs --wait
```

Each run takes roughly 3–4 minutes (build ≈ 55s, two deploys).

> **Two gotchas, learned the hard way:**
> 1. `gcloud builds submit` exits **non-zero** for a service account that is not a
>    project Viewer/Owner, because it cannot stream build logs — even when the
>    build itself succeeds. `scripts/refresh.sh` tolerates that exit code and
>    verifies the build independently.
> 2. `gcloud run deploy` needs `--flag=value` syntax when the value begins with
>    `-` (as `--args` does), or it parses the value as a flag and prints help.

- **Monitor**: `/health` and `/stats`; alert if `/health` is non-200. There is
  currently no alert if a refresh run fails — see `SECURITY.md` §5.6.
- **Scale**: stateless, read-mostly. One instance serves far more than the
  expected traffic.

## Minimum human checklist

- [x] GitHub account, repo pushed
- [x] Google Cloud project `verity-labs`, billing linked
- [x] Both services deployed and verified live
- [x] Daily refresh scheduled and verified
- [x] Published to the official MCP Registry
- [ ] Upload the profile avatar — GitHub has **no API for this**; use
      Settings → Profile → Upload (`assets/logo.png`)
- [ ] (Later) Wire payment: Stripe metered billing or x402/USDC wallet
- [ ] (Later) List in Smithery / mcp.so / Glama / PulseMCP


Everything else is already built.
