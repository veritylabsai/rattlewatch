<p align="center">
  <img src="assets/banner.png" alt="Verity — cited ground truth for AI agents" width="760">
</p>

**Cited, current, versioned ground truth for AI agents** — in the one domain where
hallucination is most expensive: cross-border product compliance.

**Live API:** https://verity-api-243195959173.us-central1.run.app
**MCP endpoint:** https://verity-api-243195959173.us-central1.run.app/mcp
**Interactive docs:** https://verity-api-243195959173.us-central1.run.app/docs

Machine-readable discovery, for agents rather than browsers:

| Document | URL |
|---|---|
| `llms.txt` | [/llms.txt](https://verity-api-243195959173.us-central1.run.app/llms.txt) |
| MCP server card | [/\.well-known/mcp/server.json](https://verity-api-243195959173.us-central1.run.app/.well-known/mcp/server.json) |

One container serves **both** surfaces — the REST API and MCP over streamable
HTTP at `/mcp`. That matters for registry discovery: directories introspect the
image's default command, so it has to be a working MCP server.

```bash
curl "https://verity-api-243195959173.us-central1.run.app/v1/recalls/search?q=Bistro%20Pro%20Electric%20Grill"
```


Verity answers the questions an agent cannot safely answer itself:

- *Is this product, brand, or model number subject to a recall?*
- *What certification does a children's product need to enter the US market?*
- *What did the ground truth change this week?*

Every answer carries an **official source URL** and a **last-verified date**. Verity
**never generates an answer** — it returns records that exist in its store, or it
says *"no verified record"*. Absence is an honest negative, not a guess.

---

## The trust guarantee

> An answer without a citation does not ship.

- **Cited** — every fact and recall is pinned to an official source (CPSC, EUR-Lex,
  ECHA, the European Commission, OEHHA).
- **Versioned** — facts are append-only. A changed answer creates a new version and
  a change event, never an in-place edit.
- **Current** — the store is re-verified against its upstream sources on a schedule;
  `verified_at` tells you exactly when.
- **Non-generative** — `verify()` returns only matching records. If nothing matches,
  it returns `found: false` with an explicit reason. It will not invent one.

---

## Tools (MCP)

| Tool | What it returns |
|---|---|
| `search_recalls` | Cited recall records matching a product name, brand, model, or UPC |
| `get_requirement` | Cited compliance requirements for a subject + market |
| `list_changes` | The change feed: new recalls and rule changes since a timestamp |
| `verify` | Cited records matching a claim/query, or an explicit `no verified record` |

## Data coverage

- **Recalls** — the full structured U.S. CPSC feed (consumer products) plus
  openFDA enforcement reports for **food, drug and device**. Every record carries
  a resolvable source URL: the official CPSC page, or a per-record openFDA query.
- **Requirements** — a curated set of cited cross-border product-compliance facts:
  CPSIA/Children's Product Certificate, CPSC eFiling, EU GPSR, CE marking,
  REACH SVHCs, RoHS, and California Prop 65 — each with a verbatim citation.

```bash
python -m verity build --max-recalls 5000 --fda-limit 3000   # default in the image
python -m verity build --fda-limit 0                          # CPSC only (used by CI)
```

The engine is domain-agnostic: new markets (UK, CA, AU, JP, and beyond) and new
rule sets are added as more cited facts and feeds are compiled, without code change.

---

## Quick start

```bash
python -m venv .venv && .venv/Scripts/activate   # or: source .venv/bin/activate
pip install -r requirements.txt

# build the store (facts + CPSC recalls)
python -m verity build

# run as an MCP server over stdio (local agents)
python -m verity mcp

# or serve the REST API + MCP over HTTP
python -m verity serve --host 0.0.0.0 --port 8000
```

### Connect a client

```json
{
  "mcpServers": {
    "verity": {
      "command": "python",
      "args": ["-m", "verity", "mcp"],
      "cwd": "/path/to/verity"
    }
  }
}
```

---

## REST API

| Endpoint | Tier |
|---|---|
| `GET /v1/recalls/search?q=...` | Free (rate-limited) |
| `GET /v1/requirements?subject=...&market=...` | Free |
| `GET /v1/changes?since=...` | Free |
| `POST /v1/verify` | Free |
| `GET /v1/premium/export` | Metered — returns HTTP `402` with an x402 payment requirement |

Interactive docs: `/docs`.

## Pricing

Free discovery and lookups, metered premium calls. The premium endpoint implements
the **x402** payment flow: the server returns `402 Payment Required` with a
structured payment requirement, and a paying agent retries with proof of payment.
This is the monetization thesis in one endpoint — *agents discover, agents pay*.
The payment rail (x402/USDC or Stripe metered billing) is wired at deploy time.

---

## Repository

```
verity/
  verity/
    store.py      # ground-truth store (facts, recalls, events, sources)
    compile.py    # ingest CPSC + cited rules
    engine.py     # query logic (search, verify, change feed)
    textutil.py   # normalization + matching primitives
    mcp_server.py # MCP server (stdio + streamable HTTP)
    api.py        # FastAPI REST + x402 stub
    __main__.py   # CLI: build / stats / serve / mcp
  data/rules/seed.yaml   # cited facts
  tests/test_engine.py   # correctness + no-hallucination tests
```

## Why this matters

AI generates infinite plausible text for free, so content is worth nothing. But AI
hallucinates — especially on current rules, specific numbers, and what changed last
week. Verity is the opposite of a generative model: a small, boring, cited layer of
truth that agents and the software they power can depend on when being wrong is
expensive.

## Security

See **[SECURITY.md](SECURITY.md)** for the full threat model, the implemented
controls, and — listed explicitly — what is **not** protected. Every claim there
is backed by a test in `tests/test_api.py`.

Highlights: query input bounded at two independent layers; per-client rate
limiting; API keys compared in constant time that **fail closed**; CORS denied by
default; hardened response headers; no stack-trace leakage; container runs as an
unprivileged user (UID 10001).

## Testing

```bash
export PYTHONPATH=.
python tests/test_engine.py   # 13 checks — correctness + non-hallucination
python tests/test_api.py      # 30 checks — security + abuse
```

See **[TESTING.md](TESTING.md)** for the coverage map and an explicit list of
what is *not* tested. A green run is not the same as "verified secure."

## License

**MIT** — see [LICENSE](LICENSE).

The **code** is open source; the **hosted service** is the product. Nothing about
the moat lives in the source: the defensible asset is the curated,
daily-refreshed, cited corpus and the freshness pipeline that maintains it.
Open-sourcing the code also means the citation machinery is auditable — which
matters for a product whose entire claim is that its answers can be trusted.

You can self-host it:

```bash
docker build -t verity .
docker run -p 8000:8000 verity
```

Or use the hosted endpoint: <https://verity-api-243195959173.us-central1.run.app>
