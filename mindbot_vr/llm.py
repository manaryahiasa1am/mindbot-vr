from __future__ import annotations

import json
import os
from typing import Any


def try_llm_guidance(user_message: str) -> str | None:
    provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if not provider:
        return None
    if provider == "ollama":
        return _ollama_chat(user_message)
    if provider == "openai":
        return _openai_chat(user_message)
    return None


def _ollama_chat(user_message: str) -> str | None:
    base = os.environ.get("OLLAMA_URL", "http://localhost:11434").strip()
    model = os.environ.get("OLLAMA_MODEL", "llama3.1").strip()
    if not base or not model:
        return None
    url = f"{base.rstrip('/')}/api/chat"
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a hospital triage assistant. Provide brief, safe, non-diagnostic guidance. "
                    "Do not claim certainty. Encourage emergency care for red flags."
                ),
            },
            {"role": "user", "content": user_message},
        ],
        "stream": False,
        "options": {"temperature": 0.2},
    }
    try:
        import urllib.request

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = ((data or {}).get("message") or {}).get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    except Exception:
        return None
    return None


def _openai_chat(user_message: str) -> str | None:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
    if not api_key or not model:
        return None
    url = "https://api.openai.com/v1/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a hospital triage assistant. Provide brief, safe, non-diagnostic guidance. "
                    "Do not claim certainty. Encourage emergency care for red flags."
                ),
            },
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.2,
    }
    try:
        import urllib.request

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = (((data or {}).get("choices") or [{}])[0].get("message") or {}).get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    except Exception:
        return None
    return None

