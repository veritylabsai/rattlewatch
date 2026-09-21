# Rattlewatch — registry listing copy

Use this text when listing Rattlewatch in MCP directories (mcp.so, Smithery, Glama,
PulseMCP) and the x402 Bazaar.

---

**Name:** Rattlewatch

**Tagline:** US product recall lookup for AI agents — every result cited.

**One-liner:** Cited CPSC and FDA recall data for agents, with nothing invented.

**Description:**

Rattlewatch answers a narrow question well: *is this product, brand, or model
number subject to a recall?* It covers CPSC consumer products and FDA food, drug
and device enforcement, and returns the official source URL for every record.

It also serves a small curated set of cited market-entry requirements (CPC, CPSC
eFiling, EU GPSR, CE marking, REACH SVHC, RoHS, Prop 65) — useful, but seven
facts, not a regulatory database.

Rattlewatch never generates an answer — it returns records that exist in its
store, or it reports "no verified record." Absence is an honest negative, not a
guess.

**Tools:**

- `search_recalls` — cited US recall records (CPSC consumer products; FDA food, drug and device enforcement) matching a product name, brand, model, or UPC
- `get_requirement` — cited market-entry requirements for a subject + market. A small curated set: CPSIA/CPC, eFiling, EU GPSR, CE, REACH, RoHS, Prop 65
- `list_changes` — the change feed: new recalls and rule changes since a timestamp
- `verify` — cited records matching a claim, or an explicit negative

**Why it can be trusted:**

- Citation on every record (CPSC, openFDA, EUR-Lex, ECHA, European Commission, OEHHA)
- Append-only facts with versions — changes are recorded, never overwritten
- `verified_at` timestamp on every fact
- Explicit, tested non-hallucination guarantee

**Scope, stated plainly:** the recall corpus is the product (CPSC plus openFDA
food/drug/device enforcement). The requirements set is seven cited facts, useful
as a companion but **not** a regulatory database. We would rather say so than let
a listing imply otherwise.

**Pricing:** Free discovery and lookups; metered premium calls via x402 (HTTP 402).

**Run:**

```bash
python -m rattlewatch mcp        # stdio
python -m rattlewatch serve      # REST API
python -m rattlewatch mcp --http # MCP over HTTP
```

**Tags:** `mcp`, `recalls`, `product-safety`, `compliance`, `cpsc`, `fda`,
`openfda`, `regulatory`, `ce-marking`, `gpsr`, `reach`, `rohs`, `prop65`,
`citations`, `verification`

**Links:** GitHub repo · `/docs` (OpenAPI) · `/health`
