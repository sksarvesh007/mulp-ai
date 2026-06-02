"""Shared OpenAI client — used by the live extractor, the agentic reviewer and the
LLM-as-judge eval. The base model (``gpt-5.5``) is multimodal, so document images are
sent to it directly and there is no OCR step.

Replies are parsed with ``extract_json`` (brace extraction) so any prose/fences the model
adds are tolerated. Note: the gpt-5.x family only accepts the default ``temperature``, so
we never pass ``temperature=0`` here (doing so returns a 400)."""

from __future__ import annotations

import json
from typing import Any

from app.core.config import Settings, get_settings
from app.observability.logs import get_logger, log_stage

log = get_logger("app.llm")


def _usage(resp: Any) -> dict[str, Any]:
    """Token counts + finish reason from a chat-completions response (best-effort)."""
    u = getattr(resp, "usage", None)
    out: dict[str, Any] = {}
    if u is not None:
        out["prompt_tokens"] = getattr(u, "prompt_tokens", None)
        out["completion_tokens"] = getattr(u, "completion_tokens", None)
        out["total_tokens"] = getattr(u, "total_tokens", None)
    choices = getattr(resp, "choices", None) or []
    if choices:
        out["finish_reason"] = getattr(choices[0], "finish_reason", None)
    return out


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


def _client(s: Settings):  # pragma: no cover - network
    from openai import AsyncOpenAI

    # Bound each call (the SDK default is ~10 min) so a stuck request fails fast and the
    # calling node degrades cleanly instead of hanging the pipeline + SSE stream.
    return AsyncOpenAI(
        api_key=s.openai_api_key,
        base_url=s.openai_base_url,
        timeout=s.llm_timeout_s,
        max_retries=s.llm_max_retries,
    )


async def openai_json(prompt: str, settings: Settings | None = None) -> dict[str, Any]:  # pragma: no cover - network
    """Text-only completion → JSON (e.g. the LLM-as-judge eval)."""
    s = settings or get_settings()
    with log_stage(log, "llm.text", model=s.openai_model, prompt_chars=len(prompt)) as m:
        resp = await _client(s).chat.completions.create(
            model=s.openai_model,
            messages=[{"role": "user", "content": prompt}],
        )
        data = extract_json(resp.choices[0].message.content)
        m.update(_usage(resp), parsed_keys=len(data))
    return data


async def openai_vision_json(
    prompt: str, image_urls: list[str], settings: Settings | None = None
) -> dict[str, Any]:  # pragma: no cover - network
    """Multimodal completion → JSON: the prompt plus one or more document images (base64
    data URLs). This is the live perception path — the image goes straight to the model."""
    s = settings or get_settings()
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    content += [{"type": "image_url", "image_url": {"url": url}} for url in image_urls]
    messages: Any = [{"role": "user", "content": content}]
    with log_stage(log, "llm.vision", model=s.openai_model, images=len(image_urls), prompt_chars=len(prompt)) as m:
        resp = await _client(s).chat.completions.create(model=s.openai_model, messages=messages)
        data = extract_json(resp.choices[0].message.content)
        m.update(_usage(resp), parsed_keys=len(data))
    return data
