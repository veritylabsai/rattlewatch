"""Security and abuse tests for the Verity API.

These assert the properties SECURITY.md claims. If a claim in that document is
not backed by a test here, treat the claim as unverified.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from verity.api import app  # noqa: E402
from verity.engine import MAX_QUERY_CHARS, Engine, _CORPUS_CACHE  # noqa: E402
from verity.store import Store  # noqa: E402

DB = Path(os.environ.get("VERITY_DB", Path.cwd() / "var" / "verity.sqlite3"))

_counter = {"n": 0}


_CLIENT: TestClient | None = None


def _client() -> TestClient:
    """One client for the whole suite.

    The MCP session manager can only be run once per process, so the app's
    lifespan must be entered exactly once. A fresh TestClient per request would
    try to start it repeatedly and fail with "Task group is not initialized" /
    ".run() can only be called once".
    """
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = TestClient(app)
        _CLIENT.__enter__()
    return _CLIENT


def _hdr() -> dict[str, str]:
    """Unique source address per call so rate-limit state cannot leak between tests."""
    _counter["n"] += 1
    return {"x-forwarded-for": f"10.0.0.{_counter['n'] % 250}"}


def _get(url: str, **kw):
    return _client().get(url, headers=_hdr(), **kw)


def _post(url: str, **kw):
    return _client().post(url, headers=_hdr(), **kw)


# ---- headers / information disclosure --------------------------------------


def test_security_headers_present():
    r = _get("/health")
    for header, value in {
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "referrer-policy": "no-referrer",
        "cache-control": "no-store",
    }.items():
        assert r.headers.get(header) == value, f"{header}={r.headers.get(header)!r}"


def test_health_does_not_leak_internals():
    body = _get("/health").json()
    assert body == {"status": "ok"}, body


def test_stats_exposes_freshness_but_not_internals():
    body = _get("/stats").json()
    # Freshness is intentionally public; internal operational detail is not.
    assert set(body) == {"facts", "recalls", "corpus_built_at", "data_age_hours"}, body
    assert "changes" not in body and "sources" not in body and "events" not in body
    assert body["data_age_hours"] is None or body["data_age_hours"] >= 0


def test_error_response_has_no_stack_trace():
    r = _post("/v1/verify", json={"query": "x" * (MAX_QUERY_CHARS + 1)})
    assert r.status_code == 422
    text = r.text.lower()
    for leak in ("traceback", "site-packages", "verity/", 'file "'):
        assert leak not in text, f"leaked {leak!r}"


# ---- input validation ------------------------------------------------------


def test_query_length_is_bounded():
    r = _get("/v1/recalls/search", params={"q": "a" * (MAX_QUERY_CHARS + 1)})
    assert r.status_code == 422


def test_empty_query_is_rejected():
    r = _get("/v1/recalls/search", params={"q": ""})
    assert r.status_code == 422


def test_limit_is_bounded():
    assert _get("/v1/recalls/search", params={"q": "grill", "limit": 999}).status_code == 422
    assert _get("/v1/recalls/search", params={"q": "grill", "limit": 0}).status_code == 422


def test_engine_bounds_query_independently_of_api():
    """Defence in depth: the engine must bound input even if the API layer is bypassed."""
    e = Engine(Store(DB))
    assert e.search_recalls("a" * (MAX_QUERY_CHARS + 10)) == []
    assert e.verify("a" * (MAX_QUERY_CHARS + 10))["found"] is False
    assert e.get_requirements("x" * 200) == []


def test_sql_injection_attempt_is_inert():
    payload = "'; DROP TABLE recalls; --"
    r = _get("/v1/recalls/search", params={"q": payload})
    assert r.status_code == 200
    # The store must be intact afterwards.
    assert Store(DB).stats()["recalls"] > 0


def test_oversized_body_is_rejected():
    r = _post("/v1/verify", json={"query": "x" * 100000})
    assert r.status_code in (413, 422), r.status_code


# ---- authentication / premium tier ----------------------------------------


def test_premium_fails_closed_when_no_keys_configured(monkeypatch=None):
    saved = os.environ.pop("VERITY_API_KEYS", None)
    try:
        r = _get("/v1/premium/export")
        assert r.status_code == 402, r.status_code  # no key configured -> payment path
    finally:
        if saved is not None:
            os.environ["VERITY_API_KEYS"] = saved


def test_premium_rejects_invalid_key():
    saved = os.environ.get("VERITY_API_KEYS")
    os.environ["VERITY_API_KEYS"] = "test-key-abc123"
    try:
        r = _get("/v1/premium/export")
        assert r.status_code == 402, "no key supplied falls through to payment"
        r2 = _client().get(
            "/v1/premium/export", headers={"x-api-key": "wrong", "x-forwarded-for": "10.9.9.9"}
        )
        assert r2.status_code == 402, "wrong key must not authorise"
    finally:
        if saved is None:
            os.environ.pop("VERITY_API_KEYS", None)
        else:
            os.environ["VERITY_API_KEYS"] = saved


def test_premium_accepts_valid_key():
    saved = os.environ.get("VERITY_API_KEYS")
    os.environ["VERITY_API_KEYS"] = "test-key-abc123"
    try:
        r = _client().get(
            "/v1/premium/export",
            headers={"x-api-key": "test-key-abc123", "x-forwarded-for": "10.9.9.10"},
        )
        assert r.status_code == 200, r.text
    finally:
        if saved is None:
            os.environ.pop("VERITY_API_KEYS", None)
        else:
            os.environ["VERITY_API_KEYS"] = saved


# ---- rate limiting ---------------------------------------------------------


def test_rate_limit_eventually_returns_429():
    from verity import api as api_mod

    limit = api_mod._RATE_MAX
    statuses = set()
    c = _client()
    for _ in range(limit + 3):
        r = c.get(
            "/v1/recalls/search", params={"q": "grill"}, headers={"x-forwarded-for": "10.7.7.7"}
        )
        statuses.add(r.status_code)
    assert 429 in statuses, f"rate limit never triggered over {limit + 3} requests: {statuses}"


# ---- MCP served from the same container -----------------------------------


def test_mcp_initialize_works_from_the_same_app():
    """The image default command must be a complete MCP server, because
    registries (e.g. Glama) introspect it."""
    r = _client().post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
        headers=_hdr(),
        follow_redirects=False,
    )
    assert r.status_code == 200, f"expected 200, got {r.status_code} (a redirect would break clients)"
    assert "verity" in r.text, r.text[:200]


def test_mcp_path_does_not_redirect():
    """A 307 on POST is a hazard: some MCP clients do not replay the body."""
    r = _client().post("/mcp", json={}, headers=_hdr(), follow_redirects=False)
    assert r.status_code != 307, "POST /mcp must not redirect"


# ---- machine-readable discovery -------------------------------------------


def test_llms_txt_is_served():
    r = _get("/llms.txt")
    assert r.status_code == 200
    assert "text/plain" in r.headers.get("content-type", "")
    body = r.text
    # Must describe the real tools and the real endpoint, or it is worse than absent.
    for tool in ("search_recalls", "get_requirement", "list_changes", "verify"):
        assert tool in body, f"{tool} missing from llms.txt"
    assert "/mcp" in body


def test_mcp_server_card_is_served():
    r = _get("/.well-known/mcp/server.json")
    assert r.status_code == 200
    card = r.json()
    assert card["name"] == "verity"
    assert any(t["type"] == "streamable-http" for t in card["transports"])
    assert len(card["tools"]) == 4


def test_server_card_alias_matches():
    a = _get("/.well-known/mcp/server.json").json()
    b = _get("/.well-known/mcp/server-card.json").json()
    assert a == b, "the two server-card filenames must agree"


# ---- correctness preserved -------------------------------------------------


def test_public_search_still_works():
    r = _get("/v1/recalls/search", params={"q": "Bistro Pro Electric Grill", "limit": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert body["results"][0]["source_url"].startswith("http")


def test_verify_negative_is_explicit():
    r = _post("/v1/verify", json={"query": "weather forecast for tokyo"})
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is False
    assert body["reason"] == "no verified record in the store"


def test_every_result_carries_a_source():
    r = _get("/v1/recalls/search", params={"q": "grill", "limit": 10})
    for item in r.json()["results"]:
        assert item["source_url"].startswith("http"), item


# ---- performance / DoS guard ----------------------------------------------


def test_corpus_cache_avoids_rebuilding_per_request():
    """The naive implementation re-tokenized the whole corpus per request."""
    _CORPUS_CACHE.clear()
    e = Engine(Store(DB))
    e.search_recalls("grill")  # builds
    assert _CORPUS_CACHE, "corpus was not cached"
    version_before = next(iter(_CORPUS_CACHE.values()))[0]

    t0 = time.perf_counter()
    for _ in range(20):
        e.search_recalls("grill")
    cached_elapsed = time.perf_counter() - t0

    # 20 cached searches should be fast; a per-request rebuild of 5k docs would not be.
    assert cached_elapsed < 5.0, f"20 searches took {cached_elapsed:.2f}s (cache not working?)"
    assert next(iter(_CORPUS_CACHE.values()))[0] == version_before


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
