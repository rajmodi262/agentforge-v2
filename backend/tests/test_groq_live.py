"""Live Groq integration tests (real LLM calls — no mock).

These tests exercise the parts that the mock-mode suite cannot:
- a real Groq API call returning valid JSON, with token accounting
- a full agent.run() end-to-end (build prompt -> real LLM -> parse ->
  Pydantic validation gate) producing schema-valid output

They are SKIPPED automatically when no Groq key is configured, so they
never break CI. To run them locally, ensure GROQ_API_KEY is set in
backend/.env (or the environment).
"""

import json
import asyncio

import pytest

from app.config import get_settings

_GROQ_KEY = get_settings().groq_api_key
_GROQ_MODEL = get_settings().groq_model or "llama-3.3-70b-versatile"

pytestmark = pytest.mark.skipif(
    not _GROQ_KEY,
    reason="GROQ_API_KEY not configured — skipping live Groq tests",
)


def _build_real_groq_service():
    """Construct a ClaudeService bound to Groq, bypassing global mock mode.

    conftest forces MOCK_MODE=true for the rest of the suite, so we build the
    service manually here to get a genuine (non-mock) provider.
    """
    from app.services.claude_service import ClaudeService
    from groq import Groq

    svc = ClaudeService.__new__(ClaudeService)
    svc.mock_mode = False
    svc.provider = "groq"
    svc.gemini_model = None
    svc.groq_model = _GROQ_MODEL
    client = Groq(api_key=_GROQ_KEY)
    svc.client = client
    svc._clients = {"groq": client}  # prime the lazy client cache
    svc._call_lock = asyncio.Lock()     # used by the optional inter-call throttle
    svc._last_call_ts = 0.0
    svc.degraded_to_mock = False
    return svc


def test_groq_live_returns_valid_json_with_tokens():
    """A real Groq call returns parseable JSON and accurate token counts."""
    svc = _build_real_groq_service()

    out = asyncio.run(
        svc.generate(
            system_prompt="You are a concise market analyst.",
            user_message=(
                "For an AI-powered fitness coaching app, return a JSON object "
                "with keys 'market' (string) and 'one_trend' (string)."
            ),
            agent_name="Research Agent",
        )
    )

    data = json.loads(out["content"])  # must be valid JSON
    assert isinstance(data, dict)
    assert out["tokens_used"] > 0
    assert out["cost"] >= 0.0


def test_groq_live_agent_end_to_end_validates():
    """A full agent.run() against real Groq produces schema-valid output.

    This is the end-to-end path the mock suite never covers: prompt build ->
    real LLM -> JSON parse -> Pydantic validation gate in _generate_with_retries.
    CEOAgent is used because its schema is all flat required strings, so the
    validation gate is a meaningful-but-stable assertion.
    """
    from app.agents.ceo_agent import CEOAgent
    from app.models.agent_outputs import CEOOutput

    agent = CEOAgent()
    agent.claude = _build_real_groq_service()  # inject real provider

    brief = "A food delivery app for college hostels in India"
    result = asyncio.run(agent.run(brief=brief, context={"brief": brief}))

    assert isinstance(result["output"], dict)
    assert result["tokens_used"] > 0
    # The output passed the validation gate inside run(); confirm it round-trips.
    CEOOutput(**result["output"])
