"""Deterministic patient-name matching.

Per the pinned interpretation (PLAN.md §4.1 #6): the LLM may normalize initials /
case / honorifics, but a **surname mismatch is always a hard fail** — we never bridge
different surnames (the TC003 "Arjun Mehta" vs dependent "Arjun Kumar" trap)."""

from __future__ import annotations

import re

_HONORIFICS = {"mr", "mrs", "ms", "dr", "vaidya", "shri", "smt", "md", "mbbs", "sri"}


def _tokens(name: str) -> list[str]:
    cleaned = re.sub(r"[.,]", " ", name.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return [t for t in cleaned.split(" ") if t and t not in _HONORIFICS]


def normalize_name(name: str) -> str:
    return " ".join(_tokens(name))


def name_matches(a: str | None, b: str | None) -> bool:
    """True if a and b plausibly name the same person.

    Equal after normalization → match. Otherwise surnames (last token) must be equal
    AND given-name tokens must be initial-compatible ("R." ↔ "Rajesh"). Differing
    surnames never match.
    """
    if not a or not b:
        return True  # missing data → cannot assert a mismatch
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return True
    if ta == tb:
        return True
    if ta[-1] != tb[-1]:  # surname mismatch → different person
        return False
    short, long = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    for s_tok, l_tok in zip(short[:-1], long[:-1], strict=False):
        if s_tok == l_tok:
            continue
        if len(s_tok) == 1 and l_tok.startswith(s_tok):
            continue
        if len(l_tok) == 1 and s_tok.startswith(l_tok):
            continue
        return False
    return True


def cluster_names(names: list[str]) -> list[list[str]]:
    """Greedily group names that refer to the same person."""
    clusters: list[list[str]] = []
    for n in names:
        placed = False
        for c in clusters:
            if name_matches(c[0], n):
                c.append(n)
                placed = True
                break
        if not placed:
            clusters.append([n])
    return clusters
