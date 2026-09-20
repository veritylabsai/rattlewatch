"""Ground-truth store.

The store is deliberately boring: facts, recalls, and events, each pinned to a
citation. There is no generative text anywhere in this file. An answer is either
in the store with a source, or it is not an answer.

Schema
------
facts    - curated, cited statements (rules, definitions, requirements). A fact
           is immutable once inserted; changing an answer creates a new version
           and an event, never an in-place edit.
recalls  - structured recall records from official feeds (CPSC and, later,
           other jurisdictions).
events   - the change feed: a new recall, or a fact whose answer changed.
sources  - the upstream pages/feeds we monitor, so fact freshness is checkable.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS facts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    key           TEXT    NOT NULL UNIQUE,
    kind          TEXT    NOT NULL,          -- 'requirement' | 'definition' | 'rule' | ...
    market        TEXT    NOT NULL,          -- 'US' | 'EU' | 'UK' | 'GLOBAL' | ...
    subject       TEXT    NOT NULL,          -- 'toys' | 'electronics' | 'cosmetics' | ...
    question      TEXT    NOT NULL,
    answer        TEXT    NOT NULL,
    citation_url  TEXT    NOT NULL,
    citation_text TEXT,                       -- verbatim snippet from the source
    source_name   TEXT    NOT NULL,
    verified_at   TEXT    NOT NULL,
    version       INTEGER NOT NULL DEFAULT 1,
    retired       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_facts_lookup ON facts(market, subject, retired);

CREATE TABLE IF NOT EXISTS recalls (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    recall_id      TEXT    NOT NULL UNIQUE,
    market         TEXT    NOT NULL DEFAULT 'US',
    source         TEXT    NOT NULL DEFAULT 'cpsc',
    title          TEXT    NOT NULL,
    recall_date    TEXT,
    hazard         TEXT,
    remedy         TEXT,
    entry_text     TEXT,                       -- flattened text used for matching
    source_url     TEXT    NOT NULL,
    raw_json       TEXT,
    ingested_at    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recalls_date ON recalls(recall_date DESC);

CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type   TEXT    NOT NULL,             -- 'recall' | 'fact_change'
    title        TEXT    NOT NULL,
    detail       TEXT,
    source_url   TEXT    NOT NULL,
    happened_at  TEXT    NOT NULL,
    payload      TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_happened ON events(happened_at DESC);

CREATE TABLE IF NOT EXISTS sources (
    key        TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    url        TEXT NOT NULL,
    kind       TEXT NOT NULL,                  -- 'json_api' | 'html' | 'manual'
    last_hash  TEXT,
    checked_at TEXT
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Forward-only migrations for databases created by older versions."""
        cols = {row["name"] for row in self._conn.execute("PRAGMA table_info(recalls)")}
        if "source" not in cols:
            self._conn.execute(
                "ALTER TABLE recalls ADD COLUMN source TEXT NOT NULL DEFAULT 'cpsc'"
            )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        self._conn.execute("BEGIN")
        try:
            yield self._conn
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    # ---- facts -------------------------------------------------------------

    def put_fact(
        self,
        key: str,
        kind: str,
        market: str,
        subject: str,
        question: str,
        answer: str,
        citation_url: str,
        source_name: str,
        citation_text: str | None = None,
        verified_at: str | None = None,
    ) -> int:
        """Insert a fact. If the key exists and the answer changed, bump version
        and record an event instead of overwriting (facts are append-only)."""
        answer = answer.strip()
        citation_url = citation_url.strip()
        if not answer or not citation_url:
            raise ValueError("a fact requires both an answer and a citation_url")

        existing = self._conn.execute(
            "SELECT * FROM facts WHERE key = ?", (key,)
        ).fetchone()

        if existing and existing["answer"] == answer:
            return int(existing["id"])

        with self.tx() as conn:
            if existing:
                new_version = int(existing["version"]) + 1
                cur = conn.execute(
                    """
                    UPDATE facts SET answer=?, citation_url=?, citation_text=?,
                        source_name=?, verified_at=?, version=?, retired=0
                    WHERE id=?
                    """,
                    (
                        answer,
                        citation_url,
                        citation_text,
                        source_name,
                        verified_at or utcnow(),
                        new_version,
                        existing["id"],
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO events
                        (event_type, title, detail, source_url, happened_at, payload)
                    VALUES ('fact_change', ?, ?, ?, ?, ?)
                    """,
                    (
                        f"{source_name}: {key}",
                        f"Answer changed (v{new_version}). Old: {existing['answer'][:400]}",
                        citation_url,
                        utcnow(),
                        json.dumps({"fact_key": key, "version": new_version}),
                    ),
                )
                return int(existing["id"])

            cur = conn.execute(
                """
                INSERT INTO facts
                    (key, kind, market, subject, question, answer, citation_url,
                     citation_text, source_name, verified_at, version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    key,
                    kind,
                    market,
                    subject,
                    question,
                    answer,
                    citation_url,
                    citation_text,
                    source_name,
                    verified_at or utcnow(),
                ),
            )
            return int(cur.lastrowid)

    def get_fact(self, key: str) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM facts WHERE key = ?", (key,)).fetchone()

    def find_facts(
        self, subject: str | None = None, market: str | None = None, kind: str | None = None
    ) -> list[sqlite3.Row]:
        clauses: list[str] = ["retired = 0"]
        params: list[Any] = []
        if subject:
            clauses.append("subject = ?")
            params.append(subject)
        if market:
            clauses.append("(market = ? OR market = 'GLOBAL')")
            params.append(market)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        sql = "SELECT * FROM facts WHERE " + " AND ".join(clauses) + " ORDER BY id"
        return list(self._conn.execute(sql, params).fetchall())

    def facts_by_source(self, source_name: str) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                "SELECT * FROM facts WHERE source_name = ? ORDER BY id", (source_name,)
            ).fetchall()
        )

    # ---- recalls -----------------------------------------------------------

    def upsert_recall(self, recall: dict[str, Any]) -> int:
        with self.tx() as conn:
            conn.execute(
                """
                INSERT INTO recalls
                    (recall_id, market, source, title, recall_date, hazard, remedy,
                     entry_text, source_url, raw_json, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(recall_id) DO UPDATE SET
                    title=excluded.title, recall_date=excluded.recall_date,
                    hazard=excluded.hazard, remedy=excluded.remedy,
                    entry_text=excluded.entry_text, source_url=excluded.source_url,
                    source=excluded.source, raw_json=excluded.raw_json
                """,
                (
                    recall["recall_id"],
                    recall.get("market", "US"),
                    recall.get("source", "cpsc"),
                    recall["title"],
                    recall.get("recall_date"),
                    recall.get("hazard"),
                    recall.get("remedy"),
                    recall.get("entry_text"),
                    recall["source_url"],
                    json.dumps(recall.get("raw", {}), ensure_ascii=False),
                    utcnow(),
                ),
            )
            row = conn.execute(
                "SELECT id FROM recalls WHERE recall_id = ?", (recall["recall_id"],)
            ).fetchone()
        return int(row["id"])

    def recall_by_id(self, recall_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM recalls WHERE recall_id = ?", (recall_id,)
        ).fetchone()

    def recall_count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM recalls").fetchone()[0])

    def counts_by_source(self) -> dict[str, int]:
        """Recall counts per upstream source, e.g. {'cpsc': 10016, 'fda-food': 29406}."""
        rows = self._conn.execute(
            "SELECT source, COUNT(*) AS n FROM recalls GROUP BY source ORDER BY n DESC"
        ).fetchall()
        return {row["source"]: int(row["n"]) for row in rows}

    def all_recalls(self) -> list[sqlite3.Row]:
        return list(
            self._conn.execute("SELECT * FROM recalls ORDER BY recall_date DESC").fetchall()
        )

    def corpus_version(self) -> tuple[int, int]:
        """Cheap fingerprint of the recall corpus, used to invalidate caches.

        One indexed aggregate, so it is safe to call on every request.
        """
        row = self._conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(MAX(id), 0) AS m FROM recalls"
        ).fetchone()
        return (int(row["n"]), int(row["m"]))

    def corpus_built_at(self) -> str | None:
        """When the corpus was last ingested -- i.e. when the image was built.

        This is the freshness signal. A "current ground truth" service that has
        silently stopped refreshing is worse than one that says it is stale, so
        this is exposed publicly and asserted by a scheduled health check.
        """
        row = self._conn.execute(
            "SELECT MAX(ingested_at) AS t FROM recalls"
        ).fetchone()
        return row["t"] if row and row["t"] else None

    # ---- events ------------------------------------------------------------

    def add_event(
        self,
        event_type: str,
        title: str,
        source_url: str,
        detail: str | None = None,
        happened_at: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> int:
        with self.tx() as conn:
            cur = conn.execute(
                """
                INSERT INTO events (event_type, title, detail, source_url, happened_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_type,
                    title,
                    detail,
                    source_url,
                    happened_at or utcnow(),
                    json.dumps(payload) if payload else None,
                ),
            )
        return int(cur.lastrowid)

    def events_since(self, iso_timestamp: str) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                "SELECT * FROM events WHERE happened_at > ? ORDER BY happened_at DESC",
                (iso_timestamp,),
            ).fetchall()
        )

    def recent_events(self, limit: int = 50) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                "SELECT * FROM events ORDER BY happened_at DESC LIMIT ?", (limit,)
            ).fetchall()
        )

    # ---- sources -----------------------------------------------------------

    def upsert_source(self, key: str, name: str, url: str, kind: str) -> None:
        with self.tx() as conn:
            conn.execute(
                """
                INSERT INTO sources (key, name, url, kind) VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET name=excluded.name, url=excluded.url, kind=excluded.kind
                """,
                (key, name, url, kind),
            )

    def set_source_state(self, key: str, content_hash: str) -> None:
        with self.tx() as conn:
            conn.execute(
                "UPDATE sources SET last_hash = ?, checked_at = ? WHERE key = ?",
                (content_hash, utcnow(), key),
            )

    def source(self, key: str) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM sources WHERE key = ?", (key,)).fetchone()

    def all_sources(self) -> list[sqlite3.Row]:
        return list(self._conn.execute("SELECT * FROM sources ORDER BY key").fetchall())

    # ---- reporting ---------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        row = self._conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM facts WHERE retired=0) AS facts,
              (SELECT COUNT(*) FROM recalls) AS recalls,
              (SELECT COUNT(*) FROM events) AS events,
              (SELECT COUNT(*) FROM sources) AS sources
            """
        ).fetchone()
        return dict(row)
