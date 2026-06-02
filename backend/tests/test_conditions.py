from __future__ import annotations

from app.engine.conditions import map_waiting_condition, match_exclusion


def test_diabetes_maps_to_waiting(policy) -> None:
    assert map_waiting_condition("Type 2 Diabetes Mellitus", policy) == ("diabetes", 90)
    assert map_waiting_condition("T2DM", policy) == ("diabetes", 90)


def test_hernia_does_not_match_disc_herniation(policy) -> None:
    # word-boundary fix: "Disc Herniation" must NOT match the insured "hernia"
    assert map_waiting_condition("Suspected Lumbar Disc Herniation", policy) is None


def test_no_waiting_match(policy) -> None:
    assert map_waiting_condition("Viral Fever", policy) is None
    assert map_waiting_condition(None, policy) is None
    assert map_waiting_condition("", policy) is None


def test_obesity_exclusion(policy) -> None:
    assert match_exclusion("Morbid Obesity — BMI 37", policy) == "Obesity and weight loss programs"
    assert (
        match_exclusion("Bariatric Consultation and Customised Diet Plan", policy) == "Obesity and weight loss programs"
    )


def test_no_exclusion(policy) -> None:
    assert match_exclusion("Viral Fever", policy) is None
    assert match_exclusion(None, policy) is None


def test_cosmetic_exclusion(policy) -> None:
    assert match_exclusion("Cosmetic rhinoplasty", policy) == "Cosmetic or aesthetic procedures"
