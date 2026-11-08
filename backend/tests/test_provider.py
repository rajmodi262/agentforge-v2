"""Tests for AI-service resilience: Gemini key rotation + mode honesty."""

import pytest
from app.services.claude_service import ClaudeService, get_claude_service


def _bare_service(keys):
    """A ClaudeService with just the fields the gemini-rotation path needs."""
    svc = ClaudeService.__new__(ClaudeService)
    svc._gemini_keys = list(keys)
    svc._gemini_rr = 0
    svc._gemini_client_cache = {}
    svc.gemini_model = "test-model"
    svc._gemini_client_for = lambda k: f"{k}-client"
    return svc


async def test_rotation_fails_over_on_429():
    svc = _bare_service(["k1", "k2", "k3"])
    seen = []

    async def fake_once(client, sp, um, mt):
        seen.append(client)
        if client == "k1-client":
            raise Exception("429 RESOURCE_EXHAUSTED: quota exceeded")
        return {"content": "{}", "thought": "", "tokens_used": 7, "cost": 0.0}

    svc._gemini_call_once = fake_once
    result = await svc._gemini_generate(None, "sys", "user", 50)
    assert result["tokens_used"] == 7
    assert seen == ["k1-client", "k2-client"]  # rotated past the rate-limited key


async def test_rotation_advances_cursor_between_calls():
    svc = _bare_service(["k1", "k2"])

    async def fake_once(client, sp, um, mt):
        return {"content": "{}", "thought": "", "tokens_used": 1, "cost": 0.0, "_client": client}

    svc._gemini_call_once = fake_once
    r1 = await svc._gemini_generate(None, "s", "u", 50)
    r2 = await svc._gemini_generate(None, "s", "u", 50)
    # round-robin: consecutive calls use different keys
    assert r1["_client"] != r2["_client"]


async def test_non_rate_limit_error_propagates():
    svc = _bare_service(["k1"])

    async def fake_once(client, sp, um, mt):
        raise ValueError("malformed request")  # not a 429 — should not be swallowed

    svc._gemini_call_once = fake_once
    with pytest.raises(ValueError):
        await svc._gemini_generate(None, "s", "u", 50)


async def test_verify_short_circuits_in_mock_mode():
    # The shared singleton runs in MOCK_MODE=true under tests
    svc = get_claude_service()
    assert svc.mock_mode is True
    info = await svc.verify_provider()
    assert info["mode"] == "mock"
    assert svc.mode_info()["mode"] == "mock"
