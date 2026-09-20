"""Command-line interface: build the store, inspect it, or serve."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from . import __version__
from .compile import OPENFDA_ENDPOINTS, fetch_cpsc, fetch_fda, ingest_cpsc, ingest_fda, load_facts
from .store import Store

DEFAULT_DB = Path(os.environ.get("VERITY_DB", Path.cwd() / "var" / "verity.sqlite3"))
DEFAULT_RULES = Path(__file__).resolve().parent.parent / "data" / "rules" / "seed.yaml"


def cmd_build(args: argparse.Namespace) -> int:
    store = Store(DEFAULT_DB)

    facts = load_facts(store, args.rules)
    print(f"facts: accepted={facts['accepted']} rejected={facts['rejected']}")

    cpsc = fetch_cpsc(max_records=args.max_recalls, cache_path=args.cache)
    result = ingest_cpsc(store, cpsc, max_records=args.max_recalls)
    print(f"cpsc:            new={result['new']:<6} updated={result['updated']:<6} seen={result['seen']}")

    # FDA coverage is opt-out (--fda-limit 0) so CI can stay hermetic and offline.
    if args.fda_limit > 0:
        cache_dir = str(Path(args.cache).parent) if args.cache else None
        for endpoint in OPENFDA_ENDPOINTS:
            records = fetch_fda(endpoint, limit=args.fda_limit, cache_dir=cache_dir)
            res = ingest_fda(store, records, endpoint)
            print(
                f"fda-{endpoint:<10}  new={res['new']:<6} updated={res['updated']:<6} seen={res['seen']}"
            )

    print(f"\nstore: {DEFAULT_DB}")
    for key, value in store.stats().items():
        print(f"  {key:<10} {value}")
    store.close()
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    store = Store(DEFAULT_DB)
    for key, value in store.stats().items():
        print(f"  {key:<10} {value}")
    store.close()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .api import serve

    serve(host=args.host, port=args.port)
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    import asyncio

    from .mcp_server import mcp

    if args.http:
        asyncio.run(
            mcp.run_streamable_http_async(host=args.host, port=args.port, streamable_http_path="/mcp")
        )
    else:
        asyncio.run(mcp.run_stdio_async())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="verity", description="Verity ground-truth layer")
    parser.add_argument("--version", action="version", version=f"verity {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="ingest sources into the ground-truth store")
    p.add_argument("--rules", default=str(DEFAULT_RULES))
    p.add_argument("--max-recalls", type=int, default=None)
    p.add_argument("--cache", default=None, help="path to cached CPSC JSON, or where to write it")
    p.add_argument(
        "--fda-limit",
        type=int,
        default=2000,
        help="records per openFDA endpoint (food/drug/device); 0 disables FDA ingestion",
    )
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("stats", help="show store statistics")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("serve", help="run the REST API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("mcp", help="run the MCP server (stdio or --http)")
    p.add_argument("--http", action="store_true")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_mcp)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
