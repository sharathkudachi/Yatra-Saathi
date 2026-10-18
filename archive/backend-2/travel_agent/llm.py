# travel_agent/llm.py
"""Optional LLM (Groq via the already-installed groq SDK).

Used only for language work: extracting trip fields and phrasing explanations.
Every call is fail-safe (returns None) and no LLM output ever reaches the budget
logic or the routing decisions. Disabled when GROQ_API_KEY is unset or
TRAVEL_AGENT_DISABLE_LLM=1.
"""
import json
import os
from pathlib import Path
from string import Template
from typing import Any, Dict, Optional

_PROMPTS = Path(__file__).resolve().parent / "prompts"
_TIMEOUT_SECONDS = 15.0
DEFAULT_MODEL = "openai/gpt-oss-120b"  # verified available on Groq 2026-09-24


def llm_enabled() -> bool:
    disabled = os.environ.get("TRAVEL_AGENT_DISABLE_LLM", "").lower() in ("1", "true", "yes")
    return bool(os.environ.get("GROQ_API_KEY")) and not disabled


def render_prompt(name: str, **values: Any) -> str:
    template = Template((_PROMPTS / f"{name}.txt").read_text(encoding="utf-8"))
    return template.safe_substitute({k: str(v) for k, v in values.items()})


def _client():
    from groq import Groq

    return Groq(api_key=os.environ["GROQ_API_KEY"], timeout=_TIMEOUT_SECONDS, max_retries=1)


def _generate(prompt: str, json_mode: bool) -> Optional[str]:
    if not llm_enabled():
        return None
    try:
        response = _client().chat.completions.create(
            model=os.environ.get("TRAVEL_AGENT_LLM_MODEL", DEFAULT_MODEL),
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            **({"response_format": {"type": "json_object"}} if json_mode else {}),
        )
        return (response.choices[0].message.content or "").strip() or None
    except Exception:  # network, auth, quota, SDK errors: fall back to deterministic path
        return None


def generate_json(prompt_name: str, **values: Any) -> Optional[Dict[str, Any]]:
    raw = _generate(render_prompt(prompt_name, **values), json_mode=True)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def generate_text(prompt_name: str, **values: Any) -> Optional[str]:
    return _generate(render_prompt(prompt_name, **values), json_mode=False)
