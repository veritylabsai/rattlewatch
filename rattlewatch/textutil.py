"""Lightweight text normalization for matching (shared by engine and compiler).

Kept deliberately small and dependency-free so the store and API stay portable.
"""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_IDENTIFIER_RE = re.compile(r"^[a-z0-9]*[0-9][a-z0-9]*$")

STOPWORDS = {
    # product-name noise
    "the", "and", "for", "with", "inc", "llc", "ltd", "corp", "co", "company",
    "limited", "group", "holdings", "international", "usa", "us", "new", "set",
    "pack", "pcs", "piece", "pieces", "inch", "inches", "cm", "mm", "oz", "lb",
    "color", "colour", "size", "model", "models", "item", "product", "products",
    "assorted", "multi", "all", "other", "various", "by", "of", "in", "a", "an",
    "to", "s", "x",
    # question / function words that must never be treated as content
    "what", "when", "where", "why", "how", "which", "who", "whom", "whose",
    "does", "did", "doing", "are", "was", "were", "been", "being", "have",
    "has", "had", "having", "will", "would", "shall", "should", "can", "could",
    "may", "might", "must", "need", "needs", "require", "requires", "required",
    "this", "that", "these", "those", "there", "here", "then", "than", "their",
    "they", "them", "your", "you", "our", "from", "into", "about", "between",
    "after", "before", "during", "without", "within", "only", "also", "such",
    "very", "any", "each", "per", "via", "vs", "etc", "e.g", "i.e",
}


def normalize(text: str | None) -> str:
    if not text:
        return ""
    return _NON_ALNUM.sub(" ", text.lower()).strip()


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("es") and not token.endswith("ses"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str | None) -> list[str]:
    if not text:
        return []
    return [
        _stem(tok)
        for tok in _TOKEN_RE.findall(normalize(text))
        if tok not in STOPWORDS and len(tok) > 2
    ]


def token_set(text: str | None) -> set[str]:
    return set(tokenize(text))


def is_identifier(token: str) -> bool:
    """A model/SKU/UPC-like token.

    Alphanumeric tokens (letters+digits, e.g. "es88", "lcs2201") count from
    length 3. Pure-digit strings must be length >= 5, so a stray "999" or "123"
    is not treated as a decisive identifier.
    """
    if len(token) < 3:
        return False
    has_digit = any(c.isdigit() for c in token)
    if not has_digit:
        return False
    has_letter = any(c.isalpha() for c in token)
    if has_letter:
        return True
    return len(token) >= 5
