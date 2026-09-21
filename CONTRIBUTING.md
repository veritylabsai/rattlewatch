# Contributing

Thanks for considering a contribution. Rattlewatch is MIT-licensed; contributions are
welcome under the same terms.

## The one rule that matters

> **An answer without a citation does not ship.**

Every fact in the store must carry a `citation_url` pointing at an official
source. `store.put_fact()` rejects a fact missing an answer or a citation, and
`tests/test_engine.py` asserts the invariant across the whole store. If your
change could produce an uncited answer, it will be rejected.

The second invariant: the engine **never generates**. `verify()` returns cited
records or an explicit `found: false` — it does not synthesize. There is a test
(`test_verify_never_hallucinates`) pinning that behaviour.

## Getting set up

```bash
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Build the store. Tests use a bundled fixture so this is not needed for CI,
# but it is useful locally:
python -m rattlewatch build --cache tests/fixtures/recalls.json --max-recalls 50
```

## Running the tests

```bash
export PYTHONPATH=.
python tests/test_engine.py    # correctness + non-hallucination
python tests/test_api.py       # security + abuse
```

Both suites are dependency-free self-runners and exit non-zero on failure. CI
runs them on every push, plus a container-hardening job that asserts the image
does not run as root and that security headers are served.

## Adding data

**More recalls** — feed the CPSC ingest, or add another structured feed to
`rattlewatch/compile.py`. Namespace the `recall_id` per source so IDs cannot collide.

**More cited requirements** — add entries to `data/rules/seed.yaml`. Required
fields: `key`, `kind`, `market`, `subject`, `question`, `answer`, `citation_url`,
`source_name`. Quote the source verbatim in `citation_text` where you can; leave
it empty rather than paraphrasing from memory.

## Style

- Keep dependencies minimal — every one is a supply-chain risk.
- Prefer explicit, boring code over clever code.
- Wrap any optional capability so its absence degrades gracefully rather than
  breaking the run.
- If you change behaviour described in `SECURITY.md` or `TESTING.md`, update the
  document in the same commit. A doc that overstates the system is a bug.
