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

## Ongoing operations (minimal)

- **Refresh the feed**: run `python -m verity build` on a schedule (Cloud Run
  Job / cron, or a GitHub Action). New recalls appear in `list_changes`.
- **Monitor**: `/health` and `/stats`; alert if `/health` is non-200.
- **Scale**: it's stateless SQLite + read-mostly; one Cloud Run instance serves
  far more than the expected early traffic. Add memory only if the recall set
  grows beyond ~50k records.

## Minimum human checklist

- [ ] Create GitHub account, push repo (I prepare everything; you run `git push`)
- [ ] Create Google Cloud (or Render) account, run the deploy command above
- [ ] (Later) Wire payment: Stripe metered billing or x402/USDC wallet

Everything else is already built.
