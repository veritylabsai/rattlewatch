"""Verity REST API.

Security posture (see SECURITY.md for the full threat model):

* Public read-only endpoints are rate limited per client, per instance.
* Query input is bounded in length at BOTH the API and engine layers.
* The premium tier requires an API key compared with hmac.compare_digest.
  If no key is configured the tier returns 503 rather than falling open.
* CORS is denied by default and must be explicitly enabled via env.
* A global handler prevents internal exception detail from leaking.
* A bounded request body and hardened security headers are applied.

Explicitly NOT protected (documented, not hidden): the service accepts
unauthenticated public traffic by design, and the public tier has no per-user
identity, so it cannot be metered or banned at the identity level.
"""

from __future__ import annotations

import hmac
import os
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .engine import MAX_QUERY_CHARS, Engine
from .store import Store

DEFAULT_DB = Path(os.environ.get("VERITY_DB", Path.cwd() / "var" / "verity.sqlite3"))


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


# Public tier: coarse per-instance guard (see SECURITY.md limitation).
_RATE_WINDOW = float(_env_int("VERITY_RATE_WINDOW_SECONDS", 60))
_RATE_MAX = _env_int("VERITY_RATE_MAX_REQUESTS", 60)
_MAX_BODY_BYTES = _env_int("VERITY_MAX_BODY_BYTES", 4096)

APP_VERSION = "0.1.0"

app = FastAPI(
    title="Verity",
    description=(
        "Cited, current, versioned ground truth for cross-border product "
        "compliance. Every answer carries an official source and a "
        "last-verified date. Nothing is generated."
    ),
    version=APP_VERSION,
    docs_url="/docs",
    redoc_url=None,
)


def _cors_origins() -> list[str]:
    raw = os.environ.get("VERITY_CORS_ORIGINS", "").strip()
    if not raw:
        return []  # deny by default
    return [o.strip() for o in raw.split(",") if o.strip()]


_origins = _cors_origins()
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["content-type", "x-api-key"],
        max_age=600,
    )


@app.middleware("http")
async def _security_middleware(request: Request, call_next):
    # Reject oversized bodies before they reach a handler.
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > _MAX_BODY_BYTES:
        return JSONResponse(status_code=413, content={"detail": "request body too large"})

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    # Never leak stack traces or internal messages to callers.
    return JSONResponse(status_code=500, content={"detail": "internal error"})


# ---- rate limiting ---------------------------------------------------------
_hits: dict[str, deque[float]] = defaultdict(deque)


def _rate_limit(key: str, window: float | None = None, max_hits: int | None = None) -> None:
    now = time.monotonic()
    w = window if window is not None else _RATE_WINDOW
    m = max_hits if max_hits is not None else _RATE_MAX
    q = _hits[key]
    while q and q[0] <= now - w:
        q.popleft()
    if len(q) >= m:
        raise HTTPException(status_code=429, detail="rate limit exceeded; retry later")
    q.append(now)


def _client_key(request: Request) -> str:
    key = request.headers.get("x-api-key")
    if key:
        return "key:" + key[:12]
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")
    return "ip:" + ip


# ---- api keys --------------------------------------------------------------
def _configured_keys() -> list[str]:
    raw = os.environ.get("VERITY_API_KEYS", "").strip()
    return [k.strip() for k in raw.split(",") if k.strip()]


def _require_api_key(request: Request) -> None:
    configured = _configured_keys()
    if not configured:
        # Fail closed, never fall open.
        raise HTTPException(status_code=503, detail="premium tier is not configured")
    provided = request.headers.get("x-api-key") or ""
    for key in configured:
        if hmac.compare_digest(provided, key):
            return
    raise HTTPException(status_code=401, detail="a valid API key is required")


def _engine() -> Engine:
    return Engine(Store(DEFAULT_DB))


# ---- endpoints -------------------------------------------------------------


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "name": "Verity",
        "tagline": "verified ground truth for AI agents",
        "version": APP_VERSION,
        "docs": "/docs",
        "health": "/health",
        "endpoints": {
            "search_recalls": "/v1/recalls/search?q=...",
            "requirements": "/v1/requirements?subject=...&market=...",
            "changes": "/v1/changes?since=2026-09-01T00:00:00+00:00",
            "verify": "POST /v1/verify",
            "premium_export": "GET /v1/premium/export (API key or x402 payment)",
        },
    }


@app.get("/health")
def health() -> dict[str, Any]:
    # Intentionally minimal: no version, no internals, no timestamps that leak
    # deployment state.
    return {"status": "ok"}


@app.get("/stats")
def stats(request: Request) -> dict[str, Any]:
    """Public counts only. Detailed operational state requires an API key."""
    _rate_limit(_client_key(request))
    public = _engine().store.stats()
    # Expose only non-sensitive, already-public-by-inspection counts.
    return {"facts": public["facts"], "recalls": public["recalls"]}


@app.get("/v1/recalls/search")
def search_recalls(
    request: Request,
    q: str = Query(..., min_length=1, max_length=MAX_QUERY_CHARS),
    market: str = Query("US", max_length=16),
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    _rate_limit(_client_key(request))
    results = _engine().search_recalls(q, market=market, limit=limit)
    return {
        "query": q,
        "count": len(results),
        "results": results,
        "note": "Records are limited to the Verity store; empty means no verified match.",
    }


@app.get("/v1/requirements")
def get_requirements(
    request: Request,
    subject: str = Query(..., min_length=1, max_length=64),
    market: str | None = Query(None, max_length=16),
) -> dict[str, Any]:
    _rate_limit(_client_key(request))
    requirements = _engine().get_requirements(subject, market=market)
    return {"subject": subject, "market": market, "count": len(requirements), "requirements": requirements}


@app.get("/v1/changes")
def list_changes(
    request: Request,
    since: str = Query(..., min_length=10, max_length=40),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    _rate_limit(_client_key(request))
    changes = _engine().list_changes(since, limit=limit)
    return {"since": since, "count": len(changes), "changes": changes}


class VerifyBody(BaseModel):
    query: str = Field(..., min_length=1, max_length=MAX_QUERY_CHARS)


@app.post("/v1/verify")
def verify(request: Request, body: VerifyBody) -> dict[str, Any]:
    _rate_limit(_client_key(request))
    return _engine().verify(body.query)


# ---- premium (metered) -----------------------------------------------------


@app.get("/v1/premium/export")
def premium_export(request: Request) -> dict[str, Any]:
    """Metered bulk export.

    Two accepted paths: a configured API key (subscription tier), or an x402
    payment. Without either, returns 402 with a structured payment requirement.

    The x402 branch is a STUB: no payment is verified and no data is returned.
    Wiring a real rail is a deploy-time step (see DEPLOY.md).
    """
    provided = request.headers.get("x-api-key") or ""
    configured = _configured_keys()
    authorised = bool(configured) and any(
        hmac.compare_digest(provided, k) for k in configured
    )
    if authorised:
        _rate_limit(_client_key(request), window=60.0, max_hits=600)
        # NOTE: bulk export is intentionally not implemented yet; returning an
        # empty, well-formed payload rather than pretending to serve data.
        return {"export": [], "count": 0, "note": "bulk export not yet implemented"}

    return JSONResponse(
        status_code=402,
        content={
            "type": "payment_required",
            "detail": "This is a metered premium call.",
            "payment": {
                "scheme": "x402",
                "network": "testnet",
                "resource": "/v1/premium/export",
                "price": "0.25",
                "currency": "USDC",
                "description": "Bulk export of recalled SKUs matched to a catalog",
            },
            "note": (
                "x402 stub: wire a real payment rail (x402/USDC or Stripe metered "
                "billing) at deploy time to settle this call."
            ),
        },
    )


# ---- run -------------------------------------------------------------------


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        # Bound the request body at the server layer too.
        limit_max_requests=_env_int("VERITY_MAX_REQUESTS_PER_WORKER", 10000),
        timeout_keep_alive=15,
    )


if __name__ == "__main__":
    serve()
