"""Tests for the Verity engine.

The core property under test: the engine returns ONLY cited records, and it
explicitly says "no verified record" rather than hallucinating. Every positive
result must carry a source URL.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from verity.engine import Engine  # noqa: E402
from verity.store import Store  # noqa: E402

DB = Path(os.environ.get("VERITY_DB", Path.cwd() / "var" / "verity.sqlite3"))


def _engine() -> Engine:
    return Engine(Store(DB))


def test_store_is_populated():
    stats = _engine().store.stats()
    assert stats["recalls"] > 0, "run `python -m verity build` first"
    assert stats["facts"] > 0


def test_search_finds_a_real_recall():
    hits = _engine().search_recalls("Bistro Pro Electric Grill")
    assert hits, "expected to find the Char-Broil Bistro Pro recall"
    top = hits[0]
    assert top["source_url"].startswith("http")
    assert "grill" in top["title"].lower() or "bistro" in top["title"].lower()
    assert 0 < top["score"] <= 1.0


def test_search_returns_empty_for_gibberish():
    hits = _engine().search_recalls("zzzqqq unrelated widget 99999")
    assert hits == []


def test_search_ignores_stray_short_numbers():
    """A 3-digit number is not a decisive identifier and must not match."""
    assert _engine().search_recalls("zzzqqq 999 unrelated") == []


def test_requirements_carry_citations():
    reqs = _engine().get_requirements("childrens_products", market="US")
    assert reqs, "expected the CPC requirement fact"
    for r in reqs:
        assert r["citation_url"].startswith("http"), r
        assert r["answer"].strip()


def test_verify_finds_real_record():
    result = _engine().verify("JKMAX Kids Bike Helmet")
    assert result["found"] is True
    assert result["results"]["recalls"] or result["results"]["facts"]


def test_verify_never_hallucinates():
    """A genuinely unrelated query returns an explicit negative, not a guess."""
    result = _engine().verify("what is the weather forecast for tokyo tomorrow")
    assert result["found"] is False
    assert result["reason"] == "no verified record in the store"


def test_verify_returns_relevant_fact_for_compliance_query():
    result = _engine().verify("does a children's product need a CPC certificate")
    assert result["found"] is True
    assert result["results"]["facts"], "expected the CPC requirement fact"


def test_every_recall_has_source():
    for r in _engine().store.all_recalls()[:50]:
        assert r["source_url"].startswith("http"), r["recall_id"]


def test_every_fact_has_citation():
    for f in _engine().store.find_facts():
        assert f["citation_url"].startswith("http"), f["key"]
        assert f["answer"].strip()


def test_change_feed_is_populated():
    changes = _engine().list_changes("2000-01-01T00:00:00+00:00", limit=20)
    assert changes, "expected recall events"
    for c in changes:
        assert c["source_url"].startswith("http")


def test_fda_records_map_and_are_searchable():
    """FDA enforcement records must land in the same store and be searchable.

    Hermetic: uses a synthetic record, no network.
    """
    import tempfile

    from verity.compile import _fda_date, _flatten_fda, ingest_fda

    assert _fda_date("20260813") == "2026-08-13"
    assert _fda_date("") is None
    assert _fda_date("garbage") is None

    rec = {
        "recall_number": "F-9999-2026",
        "recalling_firm": "Test Foods LLC",
        "product_description": "Test Brand Organic Spinach 5oz",
        "reason_for_recall": "Listeria monocytogenes contamination",
        "recall_initiation_date": "20260813",
        "report_date": "20260909",
        "classification": "Class I",
        "distribution_pattern": "Nationwide",
        "voluntary_mandated": "Voluntary: Firm initiated",
    }

    flat = _flatten_fda(rec, "food")
    assert flat is not None
    assert flat["recall_id"] == "fda-food-F-9999-2026", "IDs must be namespaced per source"
    assert flat["source"] == "fda-food"
    assert flat["recall_date"] == "2026-08-13"
    assert "spinach" in flat["entry_text"].lower()
    assert flat["source_url"].startswith("https://api.fda.gov/")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = Store(Path(tmp) / "t.sqlite3")
        try:
            assert ingest_fda(store, [rec], "food")["new"] == 1
            assert store.counts_by_source() == {"fda-food": 1}
            hits = Engine(store).search_recalls("organic spinach")
            assert hits, "an FDA record must be findable"
            assert hits[0]["source_url"].startswith("https://api.fda.gov/")
        finally:
            store.close()


def test_fda_record_missing_recall_number_is_skipped():
    from verity.compile import _flatten_fda

    assert _flatten_fda({"product_description": "no id"}, "food") is None


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  FAIL  {name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{'FAILED' if failures else 'OK'} ({failures} failure(s))")
    raise SystemExit(1 if failures else 0)
