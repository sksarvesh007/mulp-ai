"""Shared dependencies: the policy repository (cached) and the extractor factory."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.extraction.base import Extractor
from app.extraction.eval_extractor import EvalExtractor
from app.policy.repository import PolicyRepository


@lru_cache
def get_policy() -> PolicyRepository:
    return PolicyRepository.from_file()


@lru_cache
def _live_extractor() -> Extractor:
    """A single cached LiveExtractor so its per-``image_ref`` OCR cache is shared across
    the classify and extract fan-out workers — each uploaded document is OCR'd once."""
    from app.extraction.live_extractor import LiveExtractor

    return LiveExtractor()


def get_extractor(mode: str) -> Extractor:
    """Pick the perception backend. Eval mode is deterministic; live uses the LLM."""
    if mode == "live" and get_settings().has_llm:
        try:
            return _live_extractor()
        except Exception:  # pragma: no cover - live path optional until a key is set
            return EvalExtractor()
    return EvalExtractor()
