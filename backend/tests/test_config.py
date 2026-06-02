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


def test_has_llm_openai() -> None:
    assert Settings(openai_api_key="x").has_llm is True
    assert Settings(openai_api_key="").has_llm is False


def test_supports_vision_with_key() -> None:
    # the OpenAI base model reads images directly — vision is available whenever a key is set
    assert Settings(openai_api_key="x").supports_vision is True
    assert Settings(openai_api_key="").supports_vision is False
