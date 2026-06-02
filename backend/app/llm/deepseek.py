"""Shared DeepSeek (OpenAI-compatible) JSON client — used by the live extractor and
the LLM-as-judge eval. DeepSeek wraps JSON in ```` ```json ```` fences, so replies are
parsed with ``extract_json`` (brace extraction)."""

from __future__ import annotations

import json
from typing import Any

from app.core.config import Settings, get_settings


def extract_json(content: str | None) -> dict[str, Any]:
    """Parse a JSON object from an LLM reply, tolerating ```json fences / prose."""
    if not content:
        return {}
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        data = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


async def deepseek_json(prompt: str, settings: Settings | None = None) -> dict[str, Any]:  # pragma: no cover - network
    from openai import AsyncOpenAI

    s = settings or get_settings()
    # Bound each call (the SDK default is ~10 min) so a stuck DeepSeek request fails fast and
    # the calling node degrades cleanly instead of hanging the pipeline + SSE stream.
    client = AsyncOpenAI(
        api_key=s.deepseek_api_key,
        base_url=s.deepseek_base_url,
        timeout=s.llm_timeout_s,
        max_retries=s.llm_max_retries,
    )
    resp = await client.chat.completions.create(
        model=s.deepseek_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return extract_json(resp.choices[0].message.content)
