"""Diagnosis/treatment text matching for waiting periods and exclusions.

Maps free-text clinical strings onto the policy's ``specific_conditions`` keys and
``exclusions`` phrases via curated keyword/synonym lists. Keyword lists live here
(domain knowledge), but the day-counts and excluded phrases are read from the policy.
"""

from __future__ import annotations

import re

from app.policy.repository import PolicyRepository


def _kw_in(text: str, keyword: str) -> bool:
    """Whole-word(-phrase) match so 'hernia' does not match 'disc herniation'."""
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


# specific_conditions key  ->  trigger keywords (lowercase substrings)
_WAITING_SYNONYMS: dict[str, list[str]] = {
    "diabetes": ["diabetes", "t2dm", "type 2 diabetes", "type ii diabetes", "diabetic", "mellitus"],
    "hypertension": ["hypertension", "htn", "high blood pressure"],
    "thyroid_disorders": ["thyroid", "hypothyroid", "hyperthyroid"],
    "joint_replacement": [
        "joint replacement",
        "knee replacement",
        "hip replacement",
        "arthroplasty",
    ],
    "maternity": ["maternity", "pregnan", "delivery", "obstetric", "antenatal"],
    "mental_health": ["mental health", "depression", "anxiety", "psychiatric", "bipolar"],
    "obesity_treatment": ["obesity", "obese", "bariatric", "weight loss", "weight-loss"],
    "hernia": ["hernia"],
    "cataract": ["cataract"],
}

# excluded canonical -> (trigger keywords, the policy phrase it corresponds to)
_EXCLUSION_SYNONYMS: list[tuple[list[str], str]] = [
    (
        [
            "obesity",
            "obese",
            "bariatric",
            "weight loss",
            "weight-loss",
            "diet program",
            "diet plan",
            "nutrition program",
            "morbid obesity",
        ],
        "Obesity and weight loss programs",
    ),
    (["cosmetic", "aesthetic"], "Cosmetic or aesthetic procedures"),
    (
        ["infertility", "ivf", "assisted reproduction", "fertility"],
        "Infertility and assisted reproduction",
    ),
    (["substance abuse", "de-addiction", "deaddiction", "rehab"], "Substance abuse treatment"),
    (["experimental"], "Experimental treatments"),
    (["self-inflicted", "self inflicted"], "Self-inflicted injuries"),
    (["supplement", "tonic"], "Health supplements and tonics"),
    (["vaccination", "vaccine"], "Vaccination (non-medically necessary)"),
]


def map_waiting_condition(text: str | None, policy: PolicyRepository) -> tuple[str, int] | None:
    """Return (condition_key, waiting_days) if the text matches a specific condition."""
    if not text:
        return None
    low = text.lower()
    specific = policy.specific_waiting_conditions
    for key, keywords in _WAITING_SYNONYMS.items():
        if key in specific and any(_kw_in(low, kw) for kw in keywords):
            return key, int(specific[key])
    return None


def match_exclusion(text: str | None, policy: PolicyRepository) -> str | None:
    """Return the matched policy exclusion phrase, or None."""
    if not text:
        return None
    low = text.lower()
    excluded = {e.lower(): e for e in policy.excluded_conditions}
    # synonym-driven matches first (handles obesity/bariatric/diet, cosmetic, etc.)
    for keywords, phrase in _EXCLUSION_SYNONYMS:
        if any(_kw_in(low, kw) for kw in keywords) and phrase in policy.excluded_conditions:
            return phrase
    # whole-word match against the salient head of any excluded phrase
    for low_phrase, original in excluded.items():
        head = low_phrase.split(" or ")[0].split(" and ")[0].strip()
        if head and _kw_in(low, head):
            return original
    return None
