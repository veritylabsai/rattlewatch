# Rattlewatch — registry listing copy

Use this text when listing Rattlewatch in MCP directories (mcp.so, Smithery, Glama,
PulseMCP) and the x402 Bazaar.

---

**Name:** Rattlewatch

**Tagline:** Cited, current ground truth for product-safety compliance — for AI agents.

**One-liner:** The anti-hallucination layer for cross-border product compliance.

**Description:**

Rattlewatch gives AI agents cited, current, versioned answers to the compliance
questions that are most expensive to get wrong: *Is this product, brand, or model
number subject to a recall? What certification does it need to enter a market?
What changed this week?*

Every answer carries an official source URL and a last-verified date. Rattlewatch
never generates an answer — it returns records that exist in its store, or it
reports "no verified record." Absence is an honest negative, not a guess.

**Tools:**

- `search_recalls` — cited CPSC recall records matching a product name, brand, model, or UPC
- `get_requirement` — cited compliance requirements for a subject + market (CPSIA/CPC, eFiling, EU GPSR, CE, REACH, RoHS, Prop 65)
- `list_changes` — the change feed: new recalls and rule changes since a timestamp
- `verify` — cited records matching a claim, or an explicit negative

**Why it can be trusted:**

- Citation on every record (CPSC, EUR-Lex, ECHA, European Commission, OEHHA)
- Append-only facts with versions — changes are recorded, never overwritten
- `verified_at` timestamp on every fact
- Explicit, tested non-hallucination guarantee

**Pricing:** Free discovery and lookups; metered premium calls via x402 (HTTP 402).

**Run:**

```bash
python -m rattlewatch mcp        # stdio
python -m rattlewatch serve      # REST API
python -m rattlewatch mcp --http # MCP over HTTP
```

**Tags:** `mcp`, `compliance`, `product-safety`, `recall`, `regulatory`, `cpsc`,
`ce-marking`, `gpsr`, `reach`, `rohs`, `prop65`, `ground-truth`, `verification`

**Links:** GitHub repo · `/docs` (OpenAPI) · `/health`
