"""Thin LLM layer for Phantom Hunter: structured calls with a model tier.

`tier="fast"` (extraction, high volume) and `tier="reason"` (debate, chat).
On Ollama the tier picks the local model; on cloud providers it uses the
configured provider as-is.
"""

from __future__ import annotations

import json
from typing import Optional, Type

from pydantic import BaseModel

from app.config import get_settings
from app.json_utils import loads_tolerant
from app.services.claude_service import get_claude_service


def model_for(tier: str) -> Optional[str]:
    s = get_settings()
    if tier == "fast":
        return s.phantom_extract_model or s.ollama_model
    return s.phantom_reason_model or s.ollama_model


async def structured(system: str, user: str, model_cls: Type[BaseModel], max_tokens: int = 2048,
                     tier: str = "fast", agent: str = "Phantom Hunter", num_ctx: Optional[int] = None,
                     temperature: float = 0.4) -> tuple[dict, dict]:
    """Return (parsed_dict, meta). Raises on unparseable output."""
    svc = get_claude_service()
    if svc.provider == "ollama":
        res = await svc._ollama_generate(system, user, max_tokens, schema=model_cls.model_json_schema(), model=model_for(tier),
                                         num_ctx=num_ctx, temperature=temperature)
    else:
        res = await svc.generate_structured(system, user, model_cls, agent_name=agent, max_tokens=max_tokens)
    content = res["content"]
    data = content if isinstance(content, dict) else loads_tolerant(content)
    meta = {"tokens": res.get("tokens_used", 0), "provider": res.get("provider", svc.provider),
            "model": model_for(tier) if svc.provider == "ollama" else svc.provider}
    return data, meta


async def text(system: str, user: str, max_tokens: int = 1024, tier: str = "reason") -> tuple[str, dict]:
    """Free-form JSON-mode call (used where the shape is simple)."""
    svc = get_claude_service()
    if svc.provider == "ollama":
        res = await svc._ollama_generate(system, user, max_tokens, model=model_for(tier))
    else:
        res = await svc.generate(system, user, agent_name="Phantom Hunter", max_tokens=max_tokens)
    return res["content"], {"tokens": res.get("tokens_used", 0), "provider": res.get("provider", svc.provider)}


def dumps(o) -> str:
    return json.dumps(o, ensure_ascii=False, default=str)
