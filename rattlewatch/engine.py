"""Query logic over the ground-truth store.

This is the layer agents call. It has exactly one job: return cited records that
exist, and say "no verified record" otherwise. There is no generation here --
which is the entire point of the product.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from . import textutil
from .store import Store

# Bound query size. Unbounded input goes straight into tokenization, so a huge
# string is a cheap way to burn CPU on a public endpoint.
MAX_QUERY_CHARS = 256

# Per-process corpus cache, keyed by database path.
#
# WHY THIS EXISTS: the naive implementation re-read every recall and re-tokenized
# the whole corpus on every request. On a public, unauthenticated endpoint that is
# an availability and cost problem (and a trivial remote CPU-burn). The corpus is
# built once per process and invalidated when the underlying data changes.
_CORPUS_CACHE: dict[str, dict[str, Any]] = {}


def _build_idf(token_sets) -> tuple[dict[str, float], Counter]:
    n = max(len(token_sets), 1)
    df: Counter[str] = Counter()
    for tokens in token_sets:
        for token in tokens:
            df[token] += 1
    idf = {tok: math.log((n + 1) / (count + 0.5)) for tok, count in df.items()}
    return idf, df


class Engine:
    def __init__(self, store: Store):
        self.store = store
        self.db_key = str(store.path)

    # -- cached corpus -------------------------------------------------------

    def _corpus(self) -> dict[str, Any]:
        """Return the cached corpus, rebuilt only when the data changes.

        Keys: ``entries`` (list of (recall dict, token set)), ``idf``,
        ``max_idf``, ``df``, ``df_threshold``, ``version``. Tokenization happens
        once per process rather than once per request.
        """
        version = self.store.corpus_version()
        cached = _CORPUS_CACHE.get(self.db_key)
        if cached is not None and cached["version"] == version:
            return cached

        # Materialise plain dicts rather than keeping sqlite3.Row objects alive in
        # a process-level cache: a Row holds a reference to its cursor, which on
        # Windows can keep the database file from being released.
        entries: list[tuple[dict[str, Any], set[str]]] = []
        for row in self.store.all_recalls():
            entries.append(
                (
                    {
                        "recall_id": row["recall_id"],
                        "market": row["market"],
                        "title": row["title"],
                        "recall_date": row["recall_date"],
                        "hazard": row["hazard"],
                        "source_url": row["source_url"],
                    },
                    textutil.token_set(row["entry_text"]),
                )
            )

        idf, df = _build_idf([tokens for _, tokens in entries])
        max_idf = max(idf.values()) if idf else 1.0

        # Relative distinctiveness: a token is distinctive if it appears in a
        # minority of documents. An absolute IDF cut-off (formerly idf > 0.7)
        # breaks on small corpora, where every IDF is small and therefore nothing
        # qualifies -- which meant a one-record store could never match anything.
        df_threshold = max(1, int(len(entries) * 0.5))

        corpus = {
            "version": version,
            "entries": entries,
            "idf": idf,
            "max_idf": max_idf,
            "df": df,
            "df_threshold": df_threshold,
        }
        _CORPUS_CACHE[self.db_key] = corpus
        return corpus

    def invalidate_cache(self) -> None:
        _CORPUS_CACHE.pop(self.db_key, None)


    # ---- recall search -----------------------------------------------------

    def search_recalls(
        self, query: str, market: str | None = None, limit: int = 10, threshold: float = 0.45
    ) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query or len(query) > MAX_QUERY_CHARS:
            return []

        q_tokens = textutil.token_set(query)
        if not q_tokens:
            return []

        corpus = self._corpus()
        entries = corpus["entries"]
        idf = corpus["idf"]
        max_idf = corpus["max_idf"]
        df = corpus["df"]
        df_threshold = corpus["df_threshold"]
        if market:
            entries = [(r, tokens) for r, tokens in entries if r["market"] == market]

        q_weight = sum(idf.get(t, max_idf) for t in q_tokens)
        if q_weight <= 0:
            return []

        scored: list[dict[str, Any]] = []
        for recall, r_tokens in entries:
            shared = q_tokens & r_tokens
            if not shared:
                continue
            distinctive = [
                t
                for t in shared
                if textutil.is_identifier(t) or df.get(t, 0) <= df_threshold
            ]
            if not distinctive:
                continue
            coverage = sum(idf.get(t, max_idf) for t in shared) / q_weight
            has_identifier = any(textutil.is_identifier(t) for t in shared)
            # Hard identifier (model/SKU number) is decisive.
            if has_identifier:
                coverage = min(1.0, coverage + 0.3)

            # A match resting on a single non-identifier word (e.g. "weather")
            # is noise unless that word essentially IS the query.
            if len(shared) == 1 and not has_identifier and coverage < 0.75:
                continue

            if coverage >= threshold:
                scored.append(
                    {
                        "recall_id": recall["recall_id"],
                        "title": recall["title"],
                        "recall_date": recall["recall_date"],
                        "hazard": recall["hazard"],
                        "score": round(min(coverage, 1.0), 4),
                        "source_url": recall["source_url"],
                        "matched_terms": sorted(distinctive, key=lambda t: -idf.get(t, max_idf)),
                    }
                )

        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored[:limit]

    # ---- requirements ------------------------------------------------------

    def get_requirements(self, subject: str, market: str | None = None) -> list[dict[str, Any]]:
        subject = (subject or "").strip()
        if not subject or len(subject) > 64:
            return []
        rows = self.store.find_facts(subject=subject, market=market)
        return [self._fact_to_dict(r) for r in rows]

    def get_fact(self, key: str) -> dict[str, Any] | None:
        row = self.store.get_fact(key)
        return self._fact_to_dict(row) if row else None

    @staticmethod
    def _fact_to_dict(row) -> dict[str, Any]:
        return {
            "key": row["key"],
            "kind": row["kind"],
            "market": row["market"],
            "subject": row["subject"],
            "question": row["question"],
            "answer": row["answer"],
            "citation_url": row["citation_url"],
            "citation_text": row["citation_text"],
            "source_name": row["source_name"],
            "verified_at": row["verified_at"],
            "version": row["version"],
        }

    # ---- change feed -------------------------------------------------------

    def list_changes(self, since: str, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.store.events_since(since)[:limit]
        return [
            {
                "event_type": r["event_type"],
                "title": r["title"],
                "detail": r["detail"],
                "source_url": r["source_url"],
                "happened_at": r["happened_at"],
            }
            for r in rows
        ]

    # ---- verification ------------------------------------------------------

    def verify(self, query: str) -> dict[str, Any]:
        """Check a claim/query against the store.

        Returns ONLY what is in the store, with citations. If nothing matches,
        returns an explicit negative -- it never guesses and never generates.
        """
        query = (query or "").strip()
        if not query:
            return {"found": False, "reason": "empty query", "results": []}
        if len(query) > MAX_QUERY_CHARS:
            return {"found": False, "reason": "query too long", "results": []}

        recalls = self.search_recalls(query, limit=5, threshold=0.45)
        facts = []
        # Match facts by keyword overlap against the fact's own vocabulary.
        # Require at least two shared tokens so a single stray word cannot
        # surface an unrelated fact.
        q_tokens = textutil.token_set(query)
        for fact in self.store.find_facts():
            haystack = textutil.token_set(f"{fact['question']} {fact['subject']} {fact['answer']}")
            if len(q_tokens & haystack) >= 2:
                facts.append(self._fact_to_dict(fact))

        results = {
            "recalls": recalls,
            "facts": facts[:5],
        }
        found = bool(recalls or facts)
        return {
            "found": found,
            "reason": None if found else "no verified record in the store",
            "query": query,
            "results": results,
            "note": (
                "Answers are limited to cited records in the Rattlewatch store. "
                "Absence here means 'no verified record', not a negative claim."
            ),
        }
