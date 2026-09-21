# Testing

## How to run

```bash
export PYTHONPATH=.
python tests/test_engine.py      # correctness + non-hallucination  (13 checks)
python tests/test_api.py         # security + abuse                (27 checks)
```

Each suite is self-running (no pytest required) and exits non-zero on failure.

> **Note on honesty:** this suite is meaningful but *not* exhaustive. §4 lists
> what is deliberately untested. Do not read a green run as "verified secure".

---

## 1. `tests/test_engine.py` — correctness

Asserts the product's central promise: **only cited records are returned, and
nothing is invented.**

| Check | Property |
|---|---|
| `test_store_is_populated` | Fixture sanity (fails loudly if `verity build` wasn't run) |
| `test_search_finds_a_real_recall` | Real match on real data, with a source URL |
| `test_search_returns_empty_for_gibberish` | No match for nonsense |
| `test_search_ignores_stray_short_numbers` | Regression: `"999"` must not act as a decisive identifier |
| `test_requirements_carry_citations` | Every fact has an `http` citation and a non-empty answer |
| `test_every_fact_has_citation` | Whole-store invariant |
| `test_every_recall_has_source` | Whole-store invariant |
| `test_verify_finds_real_record` | Positive path |
| `test_verify_never_hallucinates` | **Returns an explicit negative for an unrelated query** |
| `test_verify_returns_relevant_fact_for_compliance_query` | Positive fact path |
| `test_change_feed_is_populated` | Change feed returns sourced events |
| `test_fda_records_map_and_are_searchable` | openFDA records land in the same store, are namespaced per source, and are findable (hermetic — synthetic record) |
| `test_fda_record_missing_recall_number_is_skipped` | A record with no ID is skipped rather than corrupting the store |

The two most important are `test_verify_never_hallucinates` and
`test_every_fact_has_citation`. They encode the reason the product exists.

## 2. `tests/test_api.py` — security and abuse

| Group | Checks |
|---|---|
| Information disclosure | Security headers present; `/health` and `/stats` return only minimal fields; error responses contain no traceback or file paths |
| Input validation | Query length bounded; empty query rejected; `limit` bounded both ends; **engine bounds input independently of the API** (defence in depth); oversized body rejected |
| Injection | `'; DROP TABLE recalls; --` is inert and the store survives |
| Authentication | Premium fails closed with no key; wrong key does not authorise; valid key accepted; the x402 path returns 402 and never data |
| Rate limiting | 429 is actually reached under sustained requests |
| Correctness preserved | Public search still works; verify returns an explicit negative; every result carries a source |
| Performance / DoS | Corpus is cached; 20 searches complete well under a threshold that a per-request rebuild could not meet |
| Machine-readable discovery | `/llms.txt`, the MCP server card (both filenames), the Glama ownership claim, and `robots.txt` are served; the repo-root and served Glama claims cannot drift apart |
| MCP surface | `initialize` succeeds from the same app, and `/mcp` does not 307-redirect (some clients do not replay the body) |

## 3. Measured performance

The corpus cache fixed a real vulnerability. Benchmark on 3,000 recalls:

```
uncached (previous implementation):  215.1 ms/request
cached   (current):                    0.4 ms/request
speedup:                              ~560x
```

Reproduce with the benchmark in the commit history, or:

```python
from verity.engine import Engine, _CORPUS_CACHE
from verity.store import Store
import time
_CORPUS_CACHE.clear()
e = Engine(Store("var/verity.sqlite3"))
e.search_recalls("grill")                      # warm the cache
t = time.perf_counter()
for _ in range(20): e.search_recalls("grill")
print((time.perf_counter() - t) / 20)
```

## 4. NOT tested — known gaps

Listed because an unstated gap is worse than a stated one.

1. **No load, soak, or concurrency testing.** Rate-limit behaviour under
   simultaneous clients, and SQLite behaviour under concurrent reads, are untested.
2. **No fuzzing.** Input handling is tested with hand-written cases only.
3. **No coverage measurement.** Line/branch coverage has not been instrumented,
   so "39 checks pass" says nothing about the proportion of code exercised.
4. **No third-party security review or penetration test.**
5. **Deployment-level controls are unverified**: Cloud Run IAM, instance caps, and
   the absence of public buckets were configured and reviewed manually.
6. **The refresh job's *definition* is unasserted.** The job has a scheduled
   end-to-end check whose behaviour is verified, but nothing tests that the Cloud
   Run Job and Cloud Scheduler remain correctly configured. A silent
   misconfiguration would leave the corpus stale until the health check caught it
   up to 36 hours later.
7. **No lockfile or SBOM.** Dependencies are pinned by minimum version only.
8. **The MCP protocol surface is tested through the app, not as a real client.**
   `initialize` and the no-redirect behaviour are asserted (and were verified
   manually against the live endpoint with a full
   `initialize → initialized → tools/list` handshake), but no automated test
   performs the handshake as a genuine MCP client would.

## 5. What is already covered

Stated explicitly so the list above is not read as a description of the whole
system. On every push, CI (`.github/workflows/ci.yml`) runs:

1. **Both suites** against a hermetic fixture (no network) — closes the old
   "no CI" gap.
2. **A container-hardening job** that builds the image, asserts the container
   **does not run as root**, smoke-tests `/health`, and asserts the security
   headers are actually served — closes the old "container is reviewed by eye" gap.
3. **A scheduled health check** (`.github/workflows/health.yml`) that fails if the
   corpus exceeds 36 hours, so a stalled refresh cannot go unnoticed.

## 6. If you want this hardened further

In rough priority order:

1. Add `coverage.py` and a floor threshold — closes gap 3.
2. Replace per-instance rate limiting with a shared counter (Redis/Firestore) so
   the limit is global — fixes the limitation in `SECURITY.md` §5.2.
3. Move API keys into Secret Manager — closes `SECURITY.md` §5.4.
4. Assert the refresh Job and Scheduler configuration — closes gap 6.
5. Add a lockfile and SBOM; pin dependency hashes — closes gap 7.
6. Add an automated MCP client handshake test — closes gap 8.
