from __future__ import annotations

import json

import pytest

from app.policy.repository import PolicyError, PolicyNotFoundError, PolicyRepository


def test_accessors(policy: PolicyRepository) -> None:
    assert policy.policy_id == "PLUM_GHI_2024"
    assert policy.per_claim_limit == 5000
    assert policy.annual_opd_limit == 50000
    assert policy.category("CONSULTATION")["copay_percent"] == 10
    assert policy.category_optional("nonexistent") is None
    assert policy.specific_waiting_conditions["diabetes"] == 90
    assert "PRESCRIPTION" in policy.document_requirements("CONSULTATION")["required"]
    assert policy.is_network_hospital("Apollo Hospitals") is True
    assert policy.is_network_hospital(None) is False
    assert policy.is_network_hospital("Random Clinic") is False
    assert policy.member("EMP001")["name"] == "Rajesh Kumar"
    assert policy.member("ZZZ") is None
    assert "Arjun Kumar" in policy.covered_names_for("EMP001")
    assert policy.covered_names_for("ZZZ") == []
    assert policy.dependents_of("EMP002") == []
    assert policy.excluded_conditions
    assert policy.fraud_thresholds["same_day_claims_limit"] == 2
    assert policy.network_hospitals
    assert policy.pre_authorization["validity_days"] == 30
    assert policy.family_floater["enabled"] is True
    assert policy.submission_rules["minimum_claim_amount"] == 500
    assert policy.raw["policy_id"] == "PLUM_GHI_2024"
    assert policy.policy_holder["renewal_status"] == "ACTIVE"
    assert policy.waiting_periods["initial_waiting_period_days"] == 30
    assert policy.coverage["sum_insured_per_employee"] == 500000


def test_unknown_category_raises(policy: PolicyRepository) -> None:
    with pytest.raises(PolicyError):
        policy.category("NOPE")


def test_unknown_doc_requirements_raises(policy: PolicyRepository) -> None:
    with pytest.raises(PolicyError):
        policy.document_requirements("NOPE")


def test_file_not_found(tmp_path) -> None:
    with pytest.raises(PolicyNotFoundError):
        PolicyRepository.from_file(tmp_path / "missing.json")


def test_malformed_json(tmp_path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not valid json")
    with pytest.raises(PolicyError):
        PolicyRepository.from_file(p)


def test_missing_required_keys(tmp_path) -> None:
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"policy_id": "X"}))
    with pytest.raises(PolicyError):
        PolicyRepository.from_file(p)
