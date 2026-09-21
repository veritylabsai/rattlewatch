"""Verity - the verified truth layer for AI agents.

Verity gives AI agents (and the software they power) cited, current, versioned
ground truth in domains where hallucination is expensive. It is the opposite of
a generative model: it never synthesizes an answer. It only returns records that
exist in the store, each pinned to an official source and a verification date.

One hard rule is encoded here: an answer without a citation does not exist.
"""

__version__ = "0.2.0"
