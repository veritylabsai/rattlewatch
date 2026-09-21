# Roadmap and ideas

## The "citation-only retrieval" idea — one engine, many corpora

**Origin:** the operator's observation that Rattlewatch *looks* like a "truthful
MCP" but is *actually* a recall lookup, and the suggestion that the truthfulness
mechanism could be separated out as a framework, with recalls as one product
built on it.

That framing is correct, and worth recording properly, because it names the real
asset more accurately than the current marketing does.

### What is actually reusable

The engine behind Rattlewatch is small — a few hundred lines. What it guarantees
is the valuable part:

1. **No answer without a citation.** A record either exists in the store with a
   resolvable `source_url`, or the response is an explicit negative.
2. **Absence is reported, never guessed.** `found: false` means "not in the
   store", not "not true". The distinction is stated in the response itself.
3. **Append-only facts.** A changed answer creates a new version plus a change
   event; nothing is overwritten in place.
4. **`verified_at` on every fact, and freshness published at `/stats`.** A claim
   that cannot be dated cannot be audited.

Any domain where hallucination is expensive wants exactly these properties:
legal, medical, financial, regulatory, internal policy, procurement, safety.

### The honest catch

An SDK of those four rules would be **thin and easy to copy** — it is a weekend
of work. The moat was never the engine; it is the curated, refreshed, cited
corpus. This is why the repository is MIT licensed deliberately.

So the business shape is probably *not* "sell the framework". It is closer to:

> **Sell the guarantee, and use each corpus as proof.**

Concretely, the sellable thing is *hosted citation-only retrieval over a
customer's own corpus*, where the product is the auditable promise — "our agent
will answer from your documents or say it doesn't know, and every claim links to
a source" — rather than the library that implements it. Enterprises buy
hallucination liability reduction, and they buy auditability. They do not buy
500 lines of Python.

### Suggested sequencing

1. **Now:** finish positioning Rattlewatch accurately as a recall lookup. It is
   the reference implementation and the worked example of the guarantee.
2. **Then:** prove demand. Currently zero external callers, so nothing about the
   guarantee has been validated by anyone but us.
3. **Only then:** extract the engine and offer the guarantee over a second corpus
   (or a customer's own documents). If a second corpus cannot be stood up in
   days rather than weeks, the abstraction is wrong.

Recorded here rather than in a tracker because at the time of writing the
Hindsight memory API was returning 401 (no API key configured in this
environment), so this note is the durable copy.
