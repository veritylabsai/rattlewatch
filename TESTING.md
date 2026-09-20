# Testing

## How to run

```bash
export PYTHONPATH=.
python tests/test_engine.py      # correctness + non-hallucination  (11 checks)
python tests/test_api.py         # security + abuse                (18 checks)
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

1. **No automated tests for the container.** The Dockerfile's non-root user,
   build step, and image contents are reviewed by eye, not asserted.
2. **No load, soak, or concurrency testing.** Rate-limit behaviour under
   simultaneous clients, and SQLite behaviour under concurrent reads, are untested.
3. **No fuzzing.** Input handling is tested with hand-written cases only.
4. **The MCP layer is only lightly covered.** Tools were exercised manually
   (`list_tools` + `call_tool` against the built server); there is no automated
   MCP test suite, and the deployed HTTP MCP endpoint is verified by a single
   manual `initialize` probe.
5. **The refresh job has no automated test.** It was verified manually end to end
   (execution `verity-refresh-mtnbb`, status `True`, producing new revisions on
   both services), but nothing asserts it keeps working. A silent failure would
   leave the corpus stale with no alert. Recommended next step: a freshness check
   that fails if the corpus is older than N hours.
6. **No CI.** Tests are run manually; nothing prevents a regression from being
   committed.
7. **No coverage measurement.** Line/branch coverage has not been instrumented,
   so "18 checks pass" says nothing about the proportion of code exercised.
8. **No third-party security review or penetration test.**
9. **Deployment-level controls are unverified**: Cloud Run IAM, instance caps, and
   the absence of public buckets were configured and reviewed manually.

## 5. If you want this hardened further

In rough priority order:

1. Add CI (GitHub Actions) running both suites on every push — closes gap 6.
2. Add `coverage.py` and a floor threshold — closes gap 7.
3. Replace per-instance rate limiting with a shared counter (Redis/Firestore) so
   the limit is global — fixes the limitation in `SECURITY.md` §5.2.
4. Move API keys into Secret Manager — closes `SECURITY.md` §5.4.
5. Add a container test (assert UID != 0, assert no shell) — closes gap 1.
6. Fix the refresh job or replace it with a Cloud Build trigger — closes gap 5,
   and is the largest correctness gap since the corpus is currently a snapshot.
7. Add a lockfile and SBOM; pin dependency hashes — closes `SECURITY.md` §5.5.
