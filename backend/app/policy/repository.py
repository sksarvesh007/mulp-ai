"""PolicyRepository — loads ``policy_terms.json`` at runtime and exposes typed
accessors. **No policy value is hardcoded in engine logic**; every rule dereferences
the loaded document through this repository.

Contract
--------
input : a path to a policy JSON file (defaults to settings.policy_file)
output: typed lookups for coverage, categories, waiting periods, exclusions,
        pre-auth, network hospitals, document requirements, fraud thresholds, members
errors: PolicyNotFoundError (missing file), PolicyError (malformed JSON / missing keys)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import get_settings


class PolicyError(Exception):
    """Raised when the policy document is malformed or a required key is absent."""


class PolicyNotFoundError(PolicyError):
    """Raised when the policy file does not exist."""


class PolicyRepository:
    def __init__(self, data: dict[str, Any]):
        self._d = data

    # ── construction ─────────────────────────────────────────────────────────
    @classmethod
    def from_file(cls, path: str | Path | None = None) -> PolicyRepository:
        p = Path(path) if path else get_settings().policy_file
        if not p.exists():
            raise PolicyNotFoundError(f"Policy file not found: {p}")
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise PolicyError(f"Malformed policy JSON at {p}: {exc}") from exc
        if "opd_categories" not in data or "members" not in data:
            raise PolicyError("Policy file missing required top-level keys")
        return cls(data)

    # ── raw access ───────────────────────────────────────────────────────────
    @property
    def raw(self) -> dict[str, Any]:
        return self._d

    @property
    def policy_id(self) -> str:
        return self._d["policy_id"]

    # ── coverage / categories ────────────────────────────────────────────────
    @property
    def coverage(self) -> dict[str, Any]:
        return self._d["coverage"]

    @property
    def per_claim_limit(self) -> int:
        return int(self.coverage["per_claim_limit"])

    @property
    def annual_opd_limit(self) -> int:
        return int(self.coverage["annual_opd_limit"])

    @property
    def family_floater(self) -> dict[str, Any]:
        return self.coverage.get("family_floater", {})

    def category(self, name: str) -> dict[str, Any]:
        cat = self._d.get("opd_categories", {}).get(name.lower())
        if cat is None:
            raise PolicyError(f"Unknown OPD category: {name}")
        return cat

    def category_optional(self, name: str) -> dict[str, Any] | None:
        return self._d.get("opd_categories", {}).get(name.lower())

    # ── rules ────────────────────────────────────────────────────────────────
    @property
    def waiting_periods(self) -> dict[str, Any]:
        return self._d["waiting_periods"]

    @property
    def specific_waiting_conditions(self) -> dict[str, int]:
        return self._d["waiting_periods"].get("specific_conditions", {})

    @property
    def exclusions(self) -> dict[str, Any]:
        return self._d.get("exclusions", {})

    @property
    def excluded_conditions(self) -> list[str]:
        return self.exclusions.get("conditions", [])

    @property
    def pre_authorization(self) -> dict[str, Any]:
        return self._d.get("pre_authorization", {})

    @property
    def network_hospitals(self) -> list[str]:
        return self._d.get("network_hospitals", [])

    def is_network_hospital(self, hospital_name: str | None) -> bool:
        if not hospital_name:
            return False
        h = hospital_name.strip().lower()
        return any(h == nh.strip().lower() or nh.strip().lower() in h for nh in self.network_hospitals)

    @property
    def submission_rules(self) -> dict[str, Any]:
        return self._d.get("submission_rules", {})

    @property
    def fraud_thresholds(self) -> dict[str, Any]:
        return self._d.get("fraud_thresholds", {})

    def document_requirements(self, category: str) -> dict[str, list[str]]:
        reqs = self._d.get("document_requirements", {}).get(category.upper())
        if reqs is None:
            raise PolicyError(f"No document requirements for category: {category}")
        return reqs

    # ── members ──────────────────────────────────────────────────────────────
    @property
    def members(self) -> list[dict[str, Any]]:
        return self._d.get("members", [])

    def member(self, member_id: str) -> dict[str, Any] | None:
        return next((m for m in self.members if m.get("member_id") == member_id), None)

    def dependents_of(self, member_id: str) -> list[dict[str, Any]]:
        """Return dependent member records linked to the given primary member."""
        member = self.member(member_id)
        dep_ids = set(member.get("dependents", []) if member else [])
        return [m for m in self.members if m.get("member_id") in dep_ids or m.get("primary_member_id") == member_id]

    def covered_names_for(self, member_id: str) -> list[str]:
        """Names the claim's patient may legitimately match: the member + dependents."""
        names: list[str] = []
        member = self.member(member_id)
        if member:
            names.append(member["name"])
        names.extend(d["name"] for d in self.dependents_of(member_id))
        return names

    def roster_names(self) -> list[str]:
        """Every person on the policy — members and dependents alike. Used to tell a patient
        who is simply the WRONG member on this claim (on the policy, but not who it was filed
        for) apart from a patient who isn't on the policy at all."""
        return [m["name"] for m in self.members]

    @property
    def policy_holder(self) -> dict[str, Any]:
        return self._d.get("policy_holder", {})
