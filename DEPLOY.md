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

## Promotion (this is the part that needs no ongoing human)

The thesis: **discovery is inbound via agentic registries, not outbound marketing.**
Publish once, then it is findable.

1. **Push the repo to GitHub** (public). Write the description to speak to *both*
   humans and agents (the `README.md` is already agent-facing).
2. **List the MCP server** in the directories agents and developers actually search:
   - [mcp.so](https://mcp.so)
   - [Smithery](https://smithery.ai)
   - [Glama MCP registry](https://glama.ai/mcp)
   - [PulseMCP](https://pulsemcp.com)
   - the official [MCP registry](https://github.com/modelcontextprotocol/servers)
   Use the copy in `docs/registry-listing.md`.
3. **List the premium endpoint** in the [x402 Bazaar](https://docs.x402.org/extensions/bazaar)
   discovery layer once the payment rail is wired.

That is the whole promotion strategy. No ads, no social, no outreach — the
product's job is to be *discoverable, understandable, and trusted*, and every
answer carries a citation to make the "trusted" part automatic.

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
