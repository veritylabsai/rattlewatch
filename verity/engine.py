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


def _build_idf(recalls) -> dict[str, float]:
    n = max(len(recalls), 1)
    df: Counter[str] = Counter()
    for recall in recalls:
        for token in textutil.token_set(recall["entry_text"]):
            df[token] += 1
    return {tok: math.log((n + 1) / (count + 0.5)) for tok, count in df.items()}


class Engine:
    def __init__(self, store: Store):
        self.store = store

    # ---- recall search -----------------------------------------------------

    def search_recalls(
        self, query: str, market: str | None = None, limit: int = 10, threshold: float = 0.45
    ) -> list[dict[str, Any]]:
        q_tokens = textutil.token_set(query)
        if not q_tokens:
            return []

        recalls = self.store.all_recalls()
        if market:
            recalls = [r for r in recalls if r["market"] == market]
        idf = _build_idf(recalls)
        max_idf = max(idf.values()) if idf else 1.0

        q_weight = sum(idf.get(t, max_idf) for t in q_tokens)
        if q_weight <= 0:
            return []

        scored: list[dict[str, Any]] = []
        for recall in recalls:
            r_tokens = textutil.token_set(recall["entry_text"])
            shared = q_tokens & r_tokens
            if not shared:
                continue
            distinctive = [
                t for t in shared if textutil.is_identifier(t) or idf.get(t, max_idf) > 0.7
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
                "Answers are limited to cited records in the Verity store. "
                "Absence here means 'no verified record', not a negative claim."
            ),
        }
