"""Shared test fixtures."""

from __future__ import annotations

import json
import os
import pathlib

# Isolate the claims DB to a throwaway file BEFORE the app (and its store) is imported.
_TEST_DB = pathlib.Path(__file__).resolve().parents[1] / "test_claims.db"
_TEST_DB.unlink(missing_ok=True)
os.environ["DB_URL"] = f"sqlite:///{_TEST_DB}"

# Pin the advisory agent OFF for the whole suite (an OS env var overrides the .env file in
# pydantic-settings). The real app enables it via .env / render.yaml, but tests must stay
# deterministic and never make a live agent network call — the agentic tests opt back in
# explicitly via monkeypatch.setenv + get_settings.cache_clear().
os.environ["ENABLE_AGENTIC_REVIEW"] = "false"

import pytest  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.policy.repository import PolicyRepository  # noqa: E402
from app.schemas.claim import ClaimInput  # noqa: E402


@pytest.fixture(scope="session")
def policy() -> PolicyRepository:
    return PolicyRepository.from_file()


@pytest.fixture(scope="session")
def cases() -> dict[str, dict]:
    data = json.loads(get_settings().test_cases_file.read_text())
    return {c["case_id"]: c for c in data["test_cases"]}


@pytest.fixture
def make_claim():
    def _make(case: dict, **overrides) -> ClaimInput:
        payload = {**case["input"], "mode": "eval", **overrides}
        return ClaimInput(**payload)

    return _make
