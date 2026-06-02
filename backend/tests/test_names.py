from __future__ import annotations

from app.engine.names import cluster_names, name_matches, normalize_name


def test_normalize_strips_honorifics_and_punctuation() -> None:
    assert normalize_name("Dr. Arun Sharma") == "arun sharma"
    assert normalize_name("  RAJESH   KUMAR ") == "rajesh kumar"
    assert normalize_name("Vaidya T. Krishnan") == "t krishnan"


def test_initials_match_same_surname() -> None:
    assert name_matches("R. Kumar", "Rajesh Kumar") is True
    assert name_matches("Rajesh Kumar", "Rajesh Kumar") is True


def test_surname_mismatch_is_hard_fail() -> None:
    # the TC003 trap: same first name, different surname
    assert name_matches("Arjun Mehta", "Arjun Kumar") is False
    assert name_matches("Rajesh Kumar", "Arjun Mehta") is False


def test_missing_names_do_not_assert_mismatch() -> None:
    assert name_matches(None, "Rajesh Kumar") is True
    assert name_matches("", "Rajesh") is True


def test_different_given_same_surname() -> None:
    assert name_matches("Sunita Kumar", "Rajesh Kumar") is False


def test_cluster_names() -> None:
    clusters = cluster_names(["Rajesh Kumar", "R. Kumar", "Arjun Mehta"])
    assert len(clusters) == 2
    assert cluster_names([]) == []
