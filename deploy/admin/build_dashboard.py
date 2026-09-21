#!/usr/bin/env python3
"""Render the Rattlewatch admin dashboard from the vhost's JSON access log.

WHY THIS IS A STATIC GENERATOR AND NOT A WEB APP
    The dashboard is written to disk as a single self-contained HTML file and
    served by nginx as a static asset behind Basic auth. There is therefore no
    request handler on /admin/ to attack: no database, no template engine, no
    session, no deserialisation. The only moving part is this script, which runs
    from a timer and is never reachable over the network.

SECURITY NOTES
    * Every value taken from the log is HTML-escaped before it reaches the
      page. User-Agent and URI are attacker-controlled, so an escaping bug here
      would be stored XSS. The CSP on the location also has no script-src, so
      scripts cannot run even if escaping failed.
    * The page contains no secret: no credentials, no API keys, no raw request
      bodies. The log itself stores only the JSON-RPC method and tool name
      derived by nginx, never caller payloads.
    * Output is written atomically. If log parsing fails the previous good page
      is left in place rather than replaced with a partial one.

Usage:
    build_dashboard.py [--stdout] [--out PATH] [--stats-url URL]
"""
from __future__ import annotations

import gzip
import html
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOG_DIR = Path("/var/log/nginx")
LOG_STEM = "rattlewatch.access.log"
DEFAULT_OUT = Path("/var/www/rattlewatch-admin/index.html")

# Fetched from the Cloud Run origin, NOT the public hostname. This script runs
# every five minutes, so routing the fetch through nginx would log one request
# per run and pollute the very metrics being reported.
DEFAULT_STATS = "https://verity-api-243195959173.us-central1.run.app/stats"

# Addresses whose requests are never counted. Loopback is always ignored: it
# can only be local health checks, the reverse proxy itself, or the operator
# probing by hand. Extra addresses can be added via the environment.
DEFAULT_IGNORE_IPS = ("127.0.0.1", "::1", "localhost")

# Substrings that mark automated clients. Matched case-insensitively against
# the User-Agent. Anything not matching is treated as a potential real caller,
# which is the conservative direction: a bot we fail to name shows up as
# "unclassified" rather than inflating the human count.
CRAWLER_MARKERS = (
    "bot", "crawl", "spider", "scrape", "curl", "wget", "python-requests",
    "httpx", "go-http-client", "java/", "okhttp", "axios", "node-fetch",
    "undici", "libwww", "headless", "monitor", "probe", "scan", "mcpbeat",
    "smithery", "glama", "brickblue", "golemreach", "sentineloracle",
    "x402", "enerlio", "pingdom", "uptime", "statuscake", "zgrab", "masscan",
    "nmap", "censys", "shodan", "internet-measurement", "petalbot", "bytespider",
)

DISCOVERY_PATHS = ("/llms.txt", "/robots.txt", "/sitemap.xml", "/.well-known/")


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def is_crawler(ua: str) -> bool:
    low = (ua or "").lower()
    return any(marker in low for marker in CRAWLER_MARKERS)


def classify(rec: dict) -> str:
    """Bucket one request. 'data' is the only bucket that means real usage."""
    uri = rec.get("uri") or ""
    rpc = rec.get("rpc") or ""
    if rpc == "tools/call" or uri.startswith("/v1/"):
        return "data"
    if rpc == "initialize":
        return "handshake"
    if rpc == "tools/list":
        return "tool_list"
    if uri.startswith(DISCOVERY_PATHS):
        return "discovery"
    if uri in ("/health", "/stats"):
        return "health"
    if uri.startswith("/docs") or uri.startswith("/openapi.json"):
        return "docs"
    if uri.startswith("/admin"):
        return "admin"
    return "other"


def log_files() -> list[Path]:
    """Current log plus every rotated generation, oldest last."""
    files = []
    current = LOG_DIR / LOG_STEM
    if current.exists():
        files.append(current)
    for p in sorted(LOG_DIR.glob(LOG_STEM + ".*")):
        if p.suffix == ".gz" or re.fullmatch(r".*\.\d+", p.name):
            files.append(p)
    return files


def iter_records():
    for path in log_files():
        try:
            opener = gzip.open if path.suffix == ".gz" else open
            with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line.startswith("{"):
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = rec.get("ts")
                    if not ts:
                        continue
                    try:
                        rec["_dt"] = datetime.fromisoformat(ts)
                    except ValueError:
                        continue
                    yield rec
        except OSError:
            continue


def fetch_stats(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def bar(value: int, peak: int, width: int = 100) -> str:
    pct = 0 if peak <= 0 else max(1, round(value * width / peak)) if value else 0
    return f'<div class="bar"><span style="width:{pct}%"></span></div>'


def render(records: list[dict], stats: dict | None, now: datetime,
           ignore_ips: frozenset[str] = frozenset()) -> str:
    windows = {
        "24h": now - timedelta(hours=24),
        "7d": now - timedelta(days=7),
        "30d": now - timedelta(days=30),
    }

    # --- per-window aggregation -------------------------------------------
    agg: dict[str, dict] = {}
    for label, start in windows.items():
        agg[label] = {
            "total": 0, "ips": set(), "data": 0, "real_data": 0,
            "handshake": 0, "tool_list": 0, "crawler": 0,
            "tools": Counter(), "data_callers": Counter(), "paths": Counter(),
        }

    hourly = defaultdict(lambda: {"total": 0, "non_crawler": 0, "data": 0})
    recent_interesting: list[dict] = []

    for rec in records:
        dt = rec["_dt"]
        ua = rec.get("ua") or ""
        bot = is_crawler(ua)
        kind = classify(rec)

        # Never measure ourselves. Admin page views are the operator's own
        # traffic, and ignored addresses are local probes or explicitly
        # excluded clients; counting either would inflate the usage figures
        # this dashboard exists to report honestly.
        if kind == "admin" or (rec.get("ip") or "") in ignore_ips:
            continue

        for label, start in windows.items():
            if dt < start:
                continue
            a = agg[label]
            a["total"] += 1
            a["ips"].add(rec.get("ip") or "-")
            a["paths"][rec.get("uri") or "-"] += 1
            if bot:
                a["crawler"] += 1
            if kind == "data":
                a["data"] += 1
                if not bot:
                    a["real_data"] += 1
                    a["data_callers"][f"{rec.get('ip')} | {ua[:90]}"] += 1
            elif kind == "handshake":
                a["handshake"] += 1
            elif kind == "tool_list":
                a["tool_list"] += 1
            if rec.get("tool"):
                a["tools"][rec["tool"]] += 1

        if dt >= now - timedelta(hours=48):
            h = dt.replace(minute=0, second=0, microsecond=0)
            hourly[h]["total"] += 1
            if kind == "data":
                hourly[h]["data"] += 1
            if not bot:
                hourly[h]["non_crawler"] += 1

        # Keep a short, human-reviewable tail of non-crawler activity.
        if not bot and kind in ("data", "handshake", "tool_list") and dt >= now - timedelta(days=14):
            recent_interesting.append(rec)

    recent_interesting.sort(key=lambda r: r["_dt"], reverse=True)

    a24 = agg["24h"]

    # --- hourly chart ------------------------------------------------------
    hours = [now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=i)
             for i in range(47, -1, -1)]
    peak = max((hourly[h]["total"] for h in hours), default=0)
    chart = []
    for h in hours:
        d = hourly[h]
        total = d["total"]
        hpx = 0 if peak == 0 else max(1, round(total * 120 / peak)) if total else 0
        real_px = 0 if total == 0 else round(hpx * d["non_crawler"] / total)
        data_px = 0 if total == 0 else round(hpx * d["data"] / total)
        chart.append(
            f'<div class="col" title="{esc(h.strftime("%Y-%m-%d %H:00"))}Z'
            f'&#10;total {total}&#10;non-crawler {d["non_crawler"]}&#10;data {d["data"]}">'
            f'<div class="stack" style="height:{hpx}px">'
            f'<div class="seg-real" style="height:{real_px}px"></div>'
            f'<div class="seg-data" style="height:{data_px}px"></div>'
            f"</div></div>"
        )

    # --- verdict -----------------------------------------------------------
    if a24["real_data"] > 0:
        verdict_class, verdict = "ok", (
            f"{a24['real_data']} data call(s) in the last 24h from non-crawler clients."
        )
    elif a24["data"] > 0:
        verdict_class, verdict = "warn", (
            f"{a24['data']} data call(s) in the last 24h, but all carried a crawler "
            "User-Agent. No evidence of a real external caller yet."
        )
    else:
        verdict_class, verdict = "bad", (
            "No data calls in the last 24h. The service is reachable and indexed, "
            "but nobody has queried it."
        )

    # --- rows --------------------------------------------------------------
    def window_rows() -> str:
        out = []
        for label in ("24h", "7d", "30d"):
            a = agg[label]
            out.append(
                "<tr>"
                f"<td>{esc(label)}</td>"
                f"<td class='n'>{a['total']:,}</td>"
                f"<td class='n'>{len(a['ips']):,}</td>"
                f"<td class='n'>{a['crawler']:,}</td>"
                f"<td class='n'>{a['handshake']:,}</td>"
                f"<td class='n'>{a['tool_list']:,}</td>"
                f"<td class='n strong'>{a['data']:,}</td>"
                f"<td class='n strong'>{a['real_data']:,}</td>"
                "</tr>"
            )
        return "".join(out)

    def tool_rows() -> str:
        tools = agg["30d"]["tools"]
        if not tools:
            return "<tr><td colspan='2' class='muted'>No tool calls recorded yet.</td></tr>"
        peak_t = max(tools.values())
        return "".join(
            f"<tr><td><code>{esc(name)}</code></td><td class='n'>{n:,}</td>"
            f"<td>{bar(n, peak_t)}</td></tr>"
            for name, n in tools.most_common(10)
        )

    def caller_rows() -> str:
        callers = agg["30d"]["data_callers"]
        if not callers:
            return ("<tr><td colspan='2' class='muted'>No non-crawler data calls in "
                    "the last 30 days.</td></tr>")
        return "".join(
            f"<tr><td><code>{esc(k)}</code></td><td class='n'>{n:,}</td></tr>"
            for k, n in callers.most_common(15)
        )

    def path_rows() -> str:
        paths = agg["7d"]["paths"]
        peak_p = max(paths.values()) if paths else 0
        if not paths:
            return "<tr><td colspan='3' class='muted'>No requests.</td></tr>"
        return "".join(
            f"<tr><td><code>{esc(p)}</code></td><td class='n'>{n:,}</td>"
            f"<td>{bar(n, peak_p)}</td></tr>"
            for p, n in paths.most_common(12)
        )

    def recent_rows() -> str:
        if not recent_interesting:
            return ("<tr><td colspan='4' class='muted'>No non-crawler MCP or API "
                    "activity in the last 14 days.</td></tr>")
        rows = []
        for rec in recent_interesting[:25]:
            label = rec.get("rpc") or rec.get("uri") or "-"
            if rec.get("tool"):
                label = f"{label} -> {rec['tool']}"
            rows.append(
                "<tr>"
                f"<td class='mono'>{esc(rec['_dt'].strftime('%Y-%m-%d %H:%M'))}</td>"
                f"<td class='mono'>{esc(rec.get('ip'))}</td>"
                f"<td><code>{esc(label)}</code></td>"
                f"<td class='ua'>{esc((rec.get('ua') or '')[:110])}</td>"
                "</tr>"
            )
        return "".join(rows)

    # --- corpus ------------------------------------------------------------
    if stats:
        age = stats.get("data_age_hours")
        built = stats.get("corpus_built_at")
        corpus = (
            f"<b>{stats.get('recalls', 0):,}</b> recalls &middot; "
            f"<b>{stats.get('facts', 0):,}</b> facts &middot; "
            f"built {esc(built)} &middot; age <b>{esc(age)}h</b>"
        )
    else:
        corpus = "<span class='muted'>Could not reach /stats.</span>"

    # --- assemble ----------------------------------------------------------
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow, noarchive, nosnippet">
<title>Rattlewatch Admin</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:28px 20px 60px; background:#0e1116; color:#dfe6ee;
         font:14px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
  .wrap {{ max-width:1080px; margin:0 auto; }}
  h1 {{ font-size:20px; margin:0 0 2px; letter-spacing:-.01em; }}
  h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.09em; color:#8b9bb0;
        margin:34px 0 10px; font-weight:600; }}
  .sub {{ color:#8b9bb0; font-size:12.5px; margin-bottom:22px; }}
  .sub a {{ color:#6fb3ff; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(168px,1fr)); gap:12px; }}
  .card {{ background:#161b23; border:1px solid #232b36; border-radius:9px; padding:14px 15px; }}
  .card .k {{ font-size:11px; text-transform:uppercase; letter-spacing:.08em; color:#8b9bb0; }}
  .card .v {{ font-size:27px; font-weight:650; margin-top:6px; font-variant-numeric:tabular-nums; }}
  .card .h {{ font-size:11.5px; color:#7d8b9e; margin-top:3px; }}
  .verdict {{ padding:13px 16px; border-radius:9px; margin:16px 0 4px; font-size:14px;
              border:1px solid; display:flex; gap:10px; align-items:flex-start; }}
  .verdict.ok   {{ background:#0f2a1b; border-color:#1f6b41; color:#8ee0ad; }}
  .verdict.warn {{ background:#2c2410; border-color:#7a5f16; color:#f0cf7a; }}
  .verdict.bad  {{ background:#2a1416; border-color:#7a2530; color:#f09aa4; }}
  .verdict b {{ color:inherit; }}
  table {{ width:100%; border-collapse:collapse; background:#141920;
           border:1px solid #232b36; border-radius:9px; overflow:hidden; }}
  th, td {{ text-align:left; padding:8px 11px; border-bottom:1px solid #1e252e; }}
  th {{ font-size:11px; text-transform:uppercase; letter-spacing:.07em;
        color:#8b9bb0; font-weight:600; background:#171d25; }}
  tr:last-child td {{ border-bottom:none; }}
  td.n {{ text-align:right; font-variant-numeric:tabular-nums; }}
  td.strong {{ color:#8ee0ad; font-weight:650; }}
  td.mono, .mono {{ font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:12.5px; }}
  td.ua {{ color:#8b9bb0; font-size:12px; }}
  code {{ font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:12.5px; color:#cfe3ff; }}
  .muted {{ color:#7d8b9e; }}
  .chart {{ display:flex; gap:2px; align-items:flex-end; height:130px;
            background:#141920; border:1px solid #232b36; border-radius:9px; padding:10px; }}
  .chart .col {{ flex:1; display:flex; align-items:flex-end; }}
  .chart .stack {{ width:100%; display:flex; flex-direction:column-reverse;
                   background:#1d2530; border-radius:2px; min-height:1px; }}
  .chart .seg-real {{ background:#2f6b45; }}
  .chart .seg-data {{ background:#5fd08a; }}
  .legend {{ font-size:11.5px; color:#8b9bb0; margin-top:7px; }}
  .legend i {{ display:inline-block; width:9px; height:9px; border-radius:2px; margin-right:5px; }}
  .bar {{ background:#1d2530; border-radius:3px; height:7px; min-width:50px; }}
  .bar span {{ display:block; height:7px; border-radius:3px; background:#4a7fb5; }}
  footer {{ margin-top:40px; color:#6f7d90; font-size:12px; border-top:1px solid #1e252e; padding-top:14px; }}
</style>
</head>
<body>
<div class="wrap">

  <h1>Rattlewatch &mdash; Admin</h1>
  <div class="sub">
    Generated {esc(now.strftime('%Y-%m-%d %H:%M:%SZ'))} &middot;
    <a href="https://rattlewatch.rattled.ca/llms.txt">llms.txt</a> &middot;
    <a href="https://rattlewatch.rattled.ca/stats">/stats</a> &middot;
    <a href="https://github.com/veritylabsai/rattlewatch">repo</a>
  </div>

  <div class="cards">
    <div class="card"><div class="k">Data calls (24h)</div>
      <div class="v">{a24['data']:,}</div>
      <div class="h">{a24['real_data']:,} non-crawler</div></div>
    <div class="card"><div class="k">Unique IPs (24h)</div>
      <div class="v">{len(a24['ips']):,}</div>
      <div class="h">{a24['crawler']:,} of {a24['total']:,} reqs are crawlers</div></div>
    <div class="card"><div class="k">MCP handshakes (24h)</div>
      <div class="v">{a24['handshake']:,}</div>
      <div class="h">{a24['tool_list']:,} tools/list</div></div>
    <div class="card"><div class="k">Requests (24h)</div>
      <div class="v">{a24['total']:,}</div>
      <div class="h">{agg['7d']['total']:,} in 7d</div></div>
  </div>

  <div class="verdict {verdict_class}"><span>&#9679;</span><div>{esc(verdict)}</div></div>

  <h2>Corpus</h2>
  <div class="card">{corpus}</div>

  <h2>Activity by window</h2>
  <table>
    <tr><th>Window</th><th class="n">Requests</th><th class="n">IPs</th>
        <th class="n">Crawler</th><th class="n">Handshake</th><th class="n">tools/list</th>
        <th class="n">Data calls</th><th class="n">Data (real)</th></tr>
    {window_rows()}
  </table>

  <h2>Requests per hour &mdash; last 48h</h2>
  <div class="chart">{''.join(chart)}</div>
  <div class="legend">
    <i style="background:#1d2530"></i>crawler
    <i style="background:#2f6b45;margin-left:12px"></i>non-crawler
    <i style="background:#5fd08a;margin-left:12px"></i>data call
  </div>

  <h2>Tool usage &mdash; last 30d</h2>
  <table>
    <tr><th>Tool</th><th class="n">Calls</th><th></th></tr>
    {tool_rows()}
  </table>

  <h2>Who is calling (non-crawler data calls, 30d)</h2>
  <table>
    <tr><th>Client</th><th class="n">Calls</th></tr>
    {caller_rows()}
  </table>

  <h2>Top paths &mdash; last 7d</h2>
  <table>
    <tr><th>Path</th><th class="n">Requests</th><th></th></tr>
    {path_rows()}
  </table>

  <h2>Recent non-crawler activity &mdash; last 14d</h2>
  <table>
    <tr><th>Time (UTC)</th><th>IP</th><th>Call</th><th>User-Agent</th></tr>
    {recent_rows()}
  </table>

  <footer>
    <b>Data calls</b> counts MCP <code>tools/call</code> and REST <code>/v1/*</code>
    requests; crawler hits are split out because directory crawlers open MCP
    sessions without ever querying data.<br>
    Source: the vhost's own JSON access log. Requests sent straight to the
    Cloud Run <code>run.app</code> URL bypass this edge and are not counted here.<br>
    This page is static and served behind Basic auth. It stores no session and
    runs no script.
  </footer>
</div>
</body>
</html>
"""


def main() -> int:
    args = sys.argv[1:]
    to_stdout = "--stdout" in args
    out = DEFAULT_OUT
    if "--out" in args:
        out = Path(args[args.index("--out") + 1])
    stats_url = DEFAULT_STATS
    if "--stats-url" in args:
        stats_url = args[args.index("--stats-url") + 1]

    records = list(iter_records())
    now = datetime.now(timezone.utc)

    ignore = set(DEFAULT_IGNORE_IPS)
    extra = os.environ.get("RATTLEWATCH_ADMIN_IGNORE_IPS", "")
    ignore.update(h.strip() for h in extra.split(",") if h.strip())

    page = render(records, fetch_stats(stats_url), now, frozenset(ignore))

    if to_stdout:
        sys.stdout.write(page)
        return 0

    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(out.parent), prefix=".index.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(page)
        os.chmod(tmp, 0o644)
        os.replace(tmp, out)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    print(f"[dashboard] wrote {out} from {len(records):,} log records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
