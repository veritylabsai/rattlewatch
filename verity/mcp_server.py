"""Verity MCP server.

Exposes the ground-truth store to AI agents through the Model Context Protocol.
Every tool returns only cited records from the store; none of them generate.

Run modes:
  * stdio (default, for local agent use):  python -m verity.mcp_server
  * streamable HTTP (for hosting):          python -m verity.mcp_server --http --port 8000
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from . import __version__
from .engine import Engine
from .store import Store

DEFAULT_DB = Path(os.environ.get("VERITY_DB", Path.cwd() / "var" / "verity.sqlite3"))

mcp = MCPServer(
    name="verity",
    title="Verity — verified product-safety ground truth",
    description=(
        "Cited, current, versioned ground truth for cross-border product "
        "compliance (recalls, certifications, and market requirements). "
        "Returns only records that exist in the store, each pinned to an "
        "official source. Never generates an answer."
    ),
    version=__version__,
)


def _engine() -> Engine:
    store = Store(DEFAULT_DB)
    return Engine(store)


@mcp.tool(
    name="search_recalls",
    description=(
        "Search official CPSC recall records by product name, brand, model, or "
        "UPC. Returns only cited recall records from the store, each with a "
        "source URL and a match score. If nothing matches, returns an empty list "
        "rather than guessing."
    ),
)
def search_recalls(query: str, market: str = "US", limit: int = 10) -> dict:
    results = _engine().search_recalls(query, market=market, limit=limit)
    return {
        "query": query,
        "count": len(results),
        "results": results,
        "note": "Records are limited to the Verity store; empty means no verified match.",
    }


@mcp.tool(
    name="get_requirement",
    description=(
        "Get cited compliance requirements for a product subject in a given "
        "market (e.g. subject='childrens_products', market='US'). Returns facts "
        "with their official citation URL and last-verified date."
    ),
)
def get_requirement(subject: str, market: str | None = None) -> dict:
    requirements = _engine().get_requirements(subject, market=market)
    return {"subject": subject, "market": market, "count": len(requirements), "requirements": requirements}


@mcp.tool(
    name="list_changes",
    description=(
        "List ground-truth changes since an ISO-8601 timestamp (e.g. "
        "'2026-09-01T00:00:00+00:00'). Includes newly published recalls and "
        "rule changes, each with its source URL."
    ),
)
def list_changes(since: str, limit: int = 100) -> dict:
    changes = _engine().list_changes(since, limit=limit)
    return {"since": since, "count": len(changes), "changes": changes}


@mcp.tool(
    name="verify",
    description=(
        "Check a factual claim or product query against the store. Returns only "
        "cited records (recalls and facts) that match. Explicitly reports "
        "'no verified record' when nothing matches -- it never synthesizes an "
        "answer, so absence means 'not in the store', not a negative claim."
    ),
)
def verify(query: str) -> dict:
    return _engine().verify(query)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the Verity MCP server.")
    parser.add_argument("--http", action="store_true", help="serve over streamable HTTP")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.http:
        mcp.run_streamable_http_async(host=args.host, port=args.port, streamable_http_path="/mcp")
    else:
        mcp.run_stdio_async()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
