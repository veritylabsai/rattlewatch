"""Compile official sources into the ground-truth store.

Two paths:
  * ingest_cpsc  - pull the structured CPSC recall feed, flatten it, and record
                   each newly-seen recall as a change event.
  * load_facts   - load curated, cited facts (rules/requirements) from a YAML
                   file. Every fact must carry a citation or it is rejected.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import yaml

from .store import Store

log = logging.getLogger(__name__)

CPSC_API = "https://www.saferproducts.gov/RestWebServices/Recall?format=json"


def _first(items: list[dict] | None, field: str) -> str | None:
    for item in items or []:
        value = item.get(field)
        if value:
            return str(value)
    return None


def _entry_text(rec: dict) -> str:
    parts: list[str] = []
    for field in ("Title", "Description"):
        value = rec.get(field)
        if value:
            parts.append(str(value))
    for product in rec.get("Products") or []:
        for field in ("Name", "Type", "Model"):
            value = product.get(field)
            if value:
                prefix = "Model" if field == "Model" else ""
                parts.append(f"{prefix} {value}".strip())
    for upc in rec.get("ProductUPCs") or []:
        value = upc.get("UPC")
        if value:
            parts.append(f"UPC {value}")
    for mfr in rec.get("Manufacturers") or []:
        value = mfr.get("Name")
        if value:
            parts.append(str(value))
    return " | ".join(p for p in parts if p)


def _flatten(rec: dict) -> dict[str, Any]:
    return {
        "recall_id": str(rec.get("RecallID") or rec.get("RecallNumber") or ""),
        "market": "US",
        "title": str(rec.get("Title") or ""),
        "recall_date": rec.get("RecallDate"),
        "hazard": _first(rec.get("Hazards"), "Name"),
        "remedy": _first(rec.get("Remedies"), "Name"),
        "entry_text": _entry_text(rec),
        "source_url": str(rec.get("URL") or ""),
        "raw": rec,
    }


def ingest_cpsc(
    store: Store,
    data: list[dict],
    max_records: int | None = None,
) -> dict[str, int]:
    """Ingest CPSC recall records. Returns counts of new/updated records."""
    new_count = 0
    updated_count = 0
    seen = 0
    for rec in data:
        if max_records and seen >= max_records:
            break
        flat = _flatten(rec)
        if not flat["recall_id"] or not flat["title"]:
            continue
        seen += 1
        existed = store.recall_by_id(flat["recall_id"]) is not None
        store.upsert_recall(flat)
        if existed:
            updated_count += 1
        else:
            new_count += 1
            store.add_event(
                event_type="recall",
                title=f"CPSC recall: {flat['title']}",
                source_url=flat["source_url"],
                detail=flat["hazard"],
                happened_at=flat["recall_date"],
                payload={"recall_id": flat["recall_id"]},
            )
    return {"new": new_count, "updated": updated_count, "seen": seen}


def fetch_cpsc(max_records: int | None = None, cache_path: str | Path | None = None) -> list[dict]:
    """Fetch the CPSC feed, optionally from a cached copy."""
    if cache_path and Path(cache_path).exists():
        return json.loads(Path(cache_path).read_text("utf-8"))
    log.info("fetching CPSC recall feed...")
    resp = httpx.get(CPSC_API, timeout=180.0)
    resp.raise_for_status()
    data = resp.json()
    data.sort(key=lambda r: (r.get("RecallDate") or ""), reverse=True)
    if cache_path:
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        Path(cache_path).write_text(json.dumps(data), "utf-8")
    return data


# ---- openFDA enforcement ---------------------------------------------------
#
# Adds food, drug and device recalls alongside CPSC consumer products. The FDA
# endpoints are free and need no auth at modest volume. Records are namespaced
# (`fda-food-...`) so IDs cannot collide with CPSC's numeric ones.

OPENFDA_ENDPOINTS = ("food", "drug", "device")
_OPENFDA_PAGE = 1000  # openFDA caps a single request at 1000


def _fda_date(raw: str | None) -> str | None:
    """openFDA dates are YYYYMMDD; normalise to ISO-8601."""
    if raw and len(raw) == 8 and raw.isdigit():
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    return None


def _flatten_fda(rec: dict, endpoint: str) -> dict[str, Any] | None:
    recall_number = (rec.get("recall_number") or "").strip()
    if not recall_number:
        return None

    firm = (rec.get("recalling_firm") or "").strip()
    product = (rec.get("product_description") or "").strip()
    reason = (rec.get("reason_for_recall") or "").strip()

    title = f"{firm} recalls {product[:90]}".strip() if product else f"FDA recall {recall_number}"
    if len(title) > 160:
        title = title[:157] + "..."

    parts = [
        product,
        reason,
        firm,
        rec.get("code_info"),
        rec.get("classification"),
        rec.get("distribution_pattern"),
    ]
    entry_text = " | ".join(p for p in parts if p)

    return {
        "recall_id": f"fda-{endpoint}-{recall_number}",
        "market": "US",
        "source": f"fda-{endpoint}",
        "title": title,
        "recall_date": _fda_date(rec.get("recall_initiation_date")) or _fda_date(rec.get("report_date")),
        "hazard": (reason[:600] or None),
        "remedy": (rec.get("voluntary_mandated") or None),
        "entry_text": entry_text,
        # A per-record, resolvable citation rather than a generic landing page.
        "source_url": (
            f"https://api.fda.gov/{endpoint}/enforcement.json"
            f"?search=recall_number:%22{quote(recall_number)}%22"
        ),
        "raw": rec,
    }


def fetch_fda(
    endpoint: str,
    limit: int = 1000,
    cache_dir: str | Path | None = None,
) -> list[dict]:
    """Fetch openFDA enforcement records for one endpoint (food|drug|device)."""
    if endpoint not in OPENFDA_ENDPOINTS:
        raise ValueError(f"unknown openFDA endpoint: {endpoint}")

    cache_file = Path(cache_dir) / f"fda_{endpoint}.json" if cache_dir else None
    if cache_file and cache_file.exists():
        return json.loads(cache_file.read_text("utf-8"))

    out: list[dict] = []
    skip = 0
    while len(out) < limit:
        page = min(_OPENFDA_PAGE, limit - len(out))
        try:
            resp = httpx.get(
                f"https://api.fda.gov/{endpoint}/enforcement.json",
                params={"limit": page, "skip": skip, "sort": "report_date:desc"},
                timeout=180.0,
            )
        except httpx.HTTPError as exc:
            log.warning("openFDA %s request failed: %s", endpoint, exc)
            break
        if resp.status_code != 200:
            log.warning("openFDA %s returned HTTP %s", endpoint, resp.status_code)
            break
        results = resp.json().get("results") or []
        if not results:
            break
        out.extend(results)
        skip += len(results)
        if len(results) < page:
            break

    out = out[:limit]
    if cache_file:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(out), "utf-8")
    return out


def ingest_fda(store: Store, records: list[dict], endpoint: str) -> dict[str, int]:
    new_count = 0
    updated_count = 0
    seen = 0
    for rec in records:
        flat = _flatten_fda(rec, endpoint)
        if not flat:
            continue
        seen += 1
        existed = store.recall_by_id(flat["recall_id"]) is not None
        store.upsert_recall(flat)
        if existed:
            updated_count += 1
        else:
            new_count += 1
            store.add_event(
                event_type="recall",
                title=f"FDA {endpoint} recall: {flat['title']}",
                source_url=flat["source_url"],
                detail=flat["hazard"],
                happened_at=flat["recall_date"],
                payload={"recall_id": flat["recall_id"], "source": flat["source"]},
            )
    return {"new": new_count, "updated": updated_count, "seen": seen}


def load_facts(store: Store, path: str | Path) -> dict[str, int]:
    """Load cited facts from a YAML file. Returns accepted/rejected counts."""
    p = Path(path)
    raw = yaml.safe_load(p.read_text("utf-8")) or {}
    entries = raw.get("facts") or []
    accepted = 0
    rejected = 0
    for entry in entries:
        required = ("key", "kind", "market", "subject", "question", "answer", "citation_url", "source_name")
        if any(not entry.get(k) for k in required):
            log.warning("rejecting fact missing required field: %s", entry.get("key"))
            rejected += 1
            continue
        store.put_fact(
            key=entry["key"],
            kind=entry["kind"],
            market=entry["market"],
            subject=entry["subject"],
            question=entry["question"],
            answer=entry["answer"],
            citation_url=entry["citation_url"],
            citation_text=entry.get("citation_text"),
            source_name=entry["source_name"],
            verified_at=entry.get("verified_at"),
        )
        accepted += 1
    return {"accepted": accepted, "rejected": rejected}
