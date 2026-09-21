"""Rattlewatch - a cited US product-recall lookup for AI agents.

Rattlewatch gives AI agents (and the software they power) cited, current recall
records: CPSC consumer products plus FDA food, drug and device enforcement. It is
the opposite of a generative model: it never synthesizes an answer. It only
returns records that exist in the store, each pinned to an official source and a
verification date. A small curated set of cited market-entry requirements ships
alongside, and is deliberately not presented as a regulatory database.

One hard rule is encoded here: an answer without a citation does not exist.
"""

__version__ = "0.2.1"
