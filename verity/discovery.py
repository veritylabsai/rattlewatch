"""Machine-readable discovery documents.

Two conventions matter for a service whose users are agents:

* ``/llms.txt`` — a plain-text summary an LLM can read to understand the service
  without scraping HTML.
* ``/.well-known/mcp/server.json`` (and ``server-card.json``) — the MCP server
  card, so directories and clients can discover the endpoint and its tools.

These are served from the running service, so they cannot drift from what the
service actually does. Keep the wording honest: describe only what is real.
"""

from __future__ import annotations

from . import __version__

MCP_URL = "https://verity-mcp-243195959173.us-central1.run.app/mcp"
API_URL = "https://verity-api-243195959173.us-central1.run.app"
REPO_URL = "https://github.com/veritylabsai/verity"

SHORT_DESCRIPTION = (
    "Cited product-compliance ground truth for AI agents. Never generates; always cites."
)

LLMS_TXT = f"""# Verity

> Cited, current ground truth for cross-border product-safety compliance, for AI agents.

Verity answers the compliance questions that are expensive to get wrong:

- Is this product, brand, or model number subject to a recall?
- What certification does a product need to enter a given market?
- What changed in the ground truth this week?

It **never generates an answer**. It returns only records that exist in its
store, each pinned to an official source URL and a last-verified date, or an
explicit `found: false` meaning "no verified record". Absence is an honest
negative, not a guess. Facts are append-only: a changed answer creates a new
version and a change event rather than an in-place edit.

## MCP endpoint

{MCP_URL}

- Transport: `streamable-http`
- Authentication: none. Public and parameterless.
- Configuration: none required.
- Verified: `initialize` -> `initialized` -> `tools/list` returns all four tools.

## Tools

- `search_recalls` — cited CPSC recall records by product name, brand, model, or UPC
- `get_requirement` — cited requirements for a subject + market (CPSIA/CPC, CPSC
  eFiling, EU GPSR, CE marking, REACH SVHCs, RoHS, California Prop 65)
- `list_changes` — new recalls and rule changes since an ISO-8601 timestamp
- `verify` — cited records matching a claim, or an explicit negative

## REST API

{API_URL}

- `GET /v1/recalls/search?q=<query>&market=US&limit=10`
- `GET /v1/requirements?subject=<subject>&market=<market>`
- `GET /v1/changes?since=<iso8601>`
- `POST /v1/verify` with `{{"query": "..."}}`
- `GET /stats` — counts, plus `corpus_built_at` and `data_age_hours` (freshness is
  deliberately public)
- `GET /docs` — OpenAPI

## Coverage

- **CPSC** (consumer products) — the full structured U.S. recall feed
- **openFDA** (food, drug, device) — enforcement reports
- **Cited requirements** — CPSIA/CPC, CPSC eFiling, EU GPSR, CE marking, REACH
  SVHCs, RoHS, California Prop 65

Every record carries a resolvable `source_url`: either the official CPSC page or
a per-record openFDA query.

## Freshness

The corpus is rebuilt daily from the upstream feeds. Check `data_age_hours` at
`/stats` before relying on an answer for anything time-critical.

## Source

{REPO_URL} (MIT)

## Limits

- Coverage is U.S. federal recall data plus a curated set of cited market
  requirements. It is **not** a complete global regulatory database, and it is
  not legal advice.
- An empty result means "not in the store", **not** "not recalled". Always
  confirm against the cited source before acting.
"""


def server_card() -> dict:
    """The MCP server card served at /.well-known/mcp/server.json."""
    return {
        "name": "verity",
        "title": "Verity",
        "description": SHORT_DESCRIPTION,
        "version": __version__,
        "homepage": REPO_URL,
        "repository": {"url": REPO_URL, "source": "github"},
        "license": "MIT",
        "transports": [
            {
                "type": "streamable-http",
                "url": MCP_URL,
                "authentication": {"type": "none"},
            }
        ],
        "tools": [
            {"name": "search_recalls", "description": "Cited CPSC recall records by product, brand, model, or UPC"},
            {"name": "get_requirement", "description": "Cited compliance requirements for a subject and market"},
            {"name": "list_changes", "description": "New recalls and rule changes since a timestamp"},
            {"name": "verify", "description": "Cited records matching a claim, or an explicit negative"},
        ],
        "documentation": {
            "llms_txt": f"{API_URL}/llms.txt",
            "openapi": f"{API_URL}/docs",
        },
    }


# Glama probes /.well-known/glama.json to verify ownership of a listing. The
# `maintainers` entry is the claim and must match the GitHub account. Serving
# this lets Glama index and verify the server without a manual submission --
# which in turn unblocks the awesome-list PRs that require a Glama badge.
GLAMA_JSON = {
    "$schema": "https://glama.ai/mcp/schemas/server.json",
    "name": "verity",
    "description": SHORT_DESCRIPTION,
    "repository": REPO_URL,
    "license": "MIT",
    "tools": 4,
    "transport": ["http"],
    "runtime": "python",
    "maintainers": ["veritylabsai"],
}


# Explicitly welcome crawlers. This service exists to be discovered by agents,
# so a missing robots.txt (previously a 404) was actively unhelpful.
ROBOTS_TXT = """# Verity is a public, read-only API intended to be found and used by agents.
# Crawlers, registries and indexers are explicitly welcome.

User-agent: *
Allow: /

# No crawl-delay: the API is rate limited per client at the edge.
"""
