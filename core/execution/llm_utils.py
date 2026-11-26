"""
core/execution/llm_utils.py

The model chain's generate() may return plain text or a dictionary, depending
on the provider wrapper. Executors call these instead of response.strip(), so
either shape works.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict


def llm_text(response: Any) -> str:
    """Return the text of a generate() result, whatever its shape."""
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        for key in ("text", "content", "response", "output", "message"):
            value = response.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, dict) and isinstance(value.get("content"), str):
                return value["content"]
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0] or {}
            message = first.get("message") or {}
            if isinstance(message.get("content"), str):
                return message["content"]
            if isinstance(first.get("text"), str):
                return first["text"]
    return str(response)


def llm_json(response: Any) -> Dict[str, Any]:
    """Parse the JSON object in a generate() result, ignoring code fences."""
    text = llm_text(response).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError(f"The model did not return JSON: {text[:200]}")
        return json.loads(match.group(0))