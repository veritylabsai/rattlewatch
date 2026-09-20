"""Verity REST API.

Free tier: recall search, requirement lookup, change feed, verification -- rate
limited, no account required.
Premium tier (x402 stub): higher limits and bulk export, metered per call.

The x402 endpoint is a demonstration of the payment model described in the
product thesis: the server returns HTTP 402 Payment Required with a structured
payment requirement, and a paying agent retries with proof. It is intentionally
a stub -- real x402 settlement requires a payment rail to be wired in at deploy
time.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .engine import Engine
from .store import Store

DEFAULT_DB = Path(os.environ.get("VERITY_DB", Path.cwd() / "var" / "verity.sqlite3"))

app = FastAPI(
    title="Verity",
    description=(
        "Cited, current, versioned ground truth for cross-border product "
        "compliance. Every answer carries an official source and a "
        "last-verified date. Nothing is generated."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ---- simple sliding-window rate limiter ------------------------------------
_FREE_WINDOW = 60.0
_FREE_MAX = 60
_hits: dict[str, deque[float]] = defaultdict(deque)


def _rate_limit(key: str, window: float = _FREE_WINDOW, max_hits: int = _FREE_MAX) -> None:
    now = time.monotonic()
    q = _hits[key]
    while q and q[0] <= now - window:
        q.popleft()
    if len(q) >= max_hits:
        raise HTTPException(status_code=429, detail="rate limit exceeded; retry later")
    q.append(now)


def _client_key(request: Request) -> str:
    return request.headers.get("x-api-key") or (request.client.host if request.client else "unknown")


def _engine() -> Engine:
    return Engine(Store(DEFAULT_DB))


# ---- endpoints -------------------------------------------------------------


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "name": "Verity",
        "tagline": "verified ground truth for AI agents",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
        "endpoints": {
            "search_recalls": "/v1/recalls/search?q=...",
            "requirements": "/v1/requirements?subject=...&market=...",
            "changes": "/v1/changes?since=2026-09-01T00:00:00+00:00",
            "verify": "POST /v1/verify",
            "premium_export": "GET /v1/premium/export (402 / x402)",
        },
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "ts": time.time()}


@app.get("/stats")
def stats() -> dict[str, Any]:
    return Engine(Store(DEFAULT_DB)).store.stats()


@app.get("/v1/recalls/search")
def search_recalls(
    request: Request,
    q: str = Query(..., description="product name, brand, model, or UPC"),
    market: str = Query("US"),
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
    subject: str = Query(..., description="childrens_products | consumer_products | electronics | chemicals | imports"),
    market: str | None = Query(None),
) -> dict[str, Any]:
    _rate_limit(_client_key(request))
    requirements = _engine().get_requirements(subject, market=market)
    return {"subject": subject, "market": market, "count": len(requirements), "requirements": requirements}


@app.get("/v1/changes")
def list_changes(
    request: Request,
    since: str = Query(..., description="ISO-8601 timestamp"),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    _rate_limit(_client_key(request))
    changes = _engine().list_changes(since, limit=limit)
    return {"since": since, "count": len(changes), "changes": changes}


class VerifyBody(BaseModel):
    query: str


@app.post("/v1/verify")
def verify(request: Request, body: VerifyBody) -> dict[str, Any]:
    _rate_limit(_client_key(request))
    return _engine().verify(body.query)


# ---- premium (x402 stub) ---------------------------------------------------


@app.get("/v1/premium/export")
def premium_export(request: Request) -> dict[str, Any]:
    """Metered bulk export. Demonstrates the x402 payment flow: returns 402 with
    a structured payment requirement instead of data, until paid."""
    from fastapi.responses import JSONResponse

    payment_requirement = {
        "scheme": "x402",
        "network": "testnet",
        "resource": "/v1/premium/export",
        "price": "0.25",
        "currency": "USDC",
        "max_required": "0.25",
        "payment_pointer": "$ilp.example.verity/premium-export",
        "description": "Bulk export of all recalled SKUs matched to a catalog",
    }
    return JSONResponse(
        status_code=402,
        content={
            "type": "payment_required",
            "detail": "This is a metered premium call.",
            "payment": payment_requirement,
            "note": (
                "x402 stub: wire a real payment rail (x402/USDC or Stripe "
                "metered billing) at deploy time to settle this call."
            ),
        },
    )


# ---- run -------------------------------------------------------------------


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    serve()
