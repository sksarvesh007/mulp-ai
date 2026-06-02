from __future__ import annotations

from pathlib import Path

from app.core.config import Settings, get_settings


def test_settings_defaults() -> None:
    s = get_settings()
    assert s.policy_file.is_absolute()
    assert s.policy_file.exists()
    assert s.test_cases_file.exists()


def test_relative_path_resolves_against_repo_root() -> None:
    s = Settings(policy_file=Path("docs/policy_terms.json"))
    assert s.policy_file.is_absolute()
    assert s.policy_file.name == "policy_terms.json"


def test_has_llm_deepseek() -> None:
    assert Settings(llm_provider="deepseek", deepseek_api_key="x").has_llm is True
    assert Settings(llm_provider="deepseek", deepseek_api_key="").has_llm is False


def test_has_llm_gemini_and_vision() -> None:
    g = Settings(llm_provider="gemini", google_api_key="x")
    assert g.has_llm is True
    assert g.supports_vision is True
    assert Settings(llm_provider="deepseek", deepseek_api_key="x").supports_vision is False
