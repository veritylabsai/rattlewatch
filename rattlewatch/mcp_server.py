"""Rattlewatch MCP server.

Exposes the ground-truth store to AI agents through the Model Context Protocol.
Every tool returns only cited records from the store; none of them generate.

Run modes:
  * stdio (default, for local agent use):  python -m rattlewatch.mcp_server
  * streamable HTTP (for hosting):          python -m rattlewatch.mcp_server --http --port 8000
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import __version__
from .engine import Engine
from .store import Store

DEFAULT_DB = Path(os.environ.get("RATTLEWATCH_DB", Path.cwd() / "var" / "rattlewatch.sqlite3"))

mcp = MCPServer(
    name="rattlewatch",
    title="Rattlewatch — cited US product recall lookup",
    description=(
        "Search US product recall data for AI agents: CPSC consumer product "
        "recalls and FDA food, drug and device enforcement reports. Returns only "
        "records that exist in the store, each pinned to an official source URL, "
        "or an explicit 'no verified record'. Never generates an answer. Also "
        "serves a small curated set of cited market-entry requirements (CPC, "
        "CPSC eFiling, EU GPSR, CE marking, REACH SVHC, RoHS, Prop 65)."
    ),
    version=__version__,
)


def _engine() -> Engine:
    store = Store(DEFAULT_DB)
    return Engine(store)


def _readonly(title: str) -> ToolAnnotations:
    """Annotations for a tool that only reads.

    Accurate rather than decorative: every Rattlewatch tool is a read-only lookup over
    a local store. Declaring it lets clients and registries treat the tools as
    safe to call, and registries that classify tools by side-effect will
    otherwise leave them unclassified.
    """
    return ToolAnnotations(
        title=title,
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    )


@mcp.tool(
    name="search_recalls",
    description=(
        "Search official US recall records by product name, brand, model, or "
        "UPC. Covers CPSC consumer products and FDA food, drug and device "
        "enforcement. Returns only cited records from the store, each with a "
        "source URL and a match score. If nothing matches, returns an empty list "
        "rather than guessing."
    ),
    annotations=_readonly("Search recalls"),
)
def search_recalls(query: str, market: str = "US", limit: int = 10) -> dict:
    results = _engine().search_recalls(query, market=market, limit=limit)
    return {
        "query": query,
        "count": len(results),
        "results": results,
        "note": "Records are limited to the Rattlewatch store; empty means no verified match.",
    }


@mcp.tool(
    name="get_requirement",
    description=(
        "Get cited market-entry requirements for a product subject in a given "
        "market (e.g. subject='childrens_products', market='US'). This is a "
        "small curated set, not a full regulatory database: CPC, CPSC eFiling, "
        "EU GPSR, CE marking, REACH SVHC, RoHS and California Prop 65. Returns "
        "each fact with its official citation URL and last-verified date."
    ),
    annotations=_readonly("Get requirement"),
)
def get_requirement(subject: str, market: str | None = None) -> dict:
    requirements = _engine().get_requirements(subject, market=market)
    return {"subject": subject, "market": market, "count": len(requirements), "requirements": requirements}


@mcp.tool(
    name="list_changes",
    description=(
        "List recall and requirement changes since an ISO-8601 timestamp (e.g. "
        "'2026-09-01T00:00:00+00:00'). Includes newly published recalls and rule "
        "changes, each with its source URL."
    ),
    annotations=_readonly("List changes"),
)
def list_changes(since: str, limit: int = 100) -> dict:
    changes = _engine().list_changes(since, limit=limit)
    return {"since": since, "count": len(changes), "changes": changes}


@mcp.tool(
    name="verify",
    description=(
        "Check a claim or product query against the store. Returns only cited "
        "records (recalls and requirements) that match. Explicitly reports "
        "'no verified record' when nothing matches -- it never synthesizes an "
        "answer, so absence means 'not in the store', not a negative claim."
    ),
    annotations=_readonly("Verify a claim"),
)
def verify(query: str) -> dict:
    return _engine().verify(query)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the Rattlewatch MCP server.")
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
