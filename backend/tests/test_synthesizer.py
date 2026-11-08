"""Tests for the Chief Synthesizer stage (coherent blueprint from all agents)."""

import json
import pytest
from app.agents.synthesizer import synthesize_blueprint, BLUEPRINT_SECTIONS


class FakeClaude:
    """Minimal stand-in for ClaudeService.generate()."""
    def __init__(self, content, tokens=321):
        self._content = content
        self._tokens = tokens
        self.last_user_message = None

    async def generate(self, system_prompt, user_message, agent_name, max_tokens):
        self.last_user_message = user_message
        return {"content": self._content, "tokens_used": self._tokens}


_AGENT_OUTPUTS = {
    "ceo_output": {"problem_statement": "x", "solution_description": "y"},
    "research_output": {"market_size": {"tam": "$5B"}},
    "finance_output": {"break_even": "month 12"},
    "board_meeting_output": {"key_risks_after_debate": ["churn"], "consensus_score": 80},
}


async def test_returns_all_canonical_sections():
    full = {s: {"filled": True} for s in BLUEPRINT_SECTIONS}
    claude = FakeClaude(json.dumps(full))
    result = await synthesize_blueprint("an idea", _AGENT_OUTPUTS, claude)
    bp = result["blueprint"]
    for s in BLUEPRINT_SECTIONS:
        assert s in bp
    assert result["tokens_used"] == 321


async def test_missing_sections_filled_with_placeholder():
    partial = {"vision_and_problem": {"v": 1}, "key_risks": ["r"]}
    claude = FakeClaude(json.dumps(partial))
    bp = (await synthesize_blueprint("idea", _AGENT_OUTPUTS, claude))["blueprint"]
    assert bp["vision_and_problem"] == {"v": 1}
    # everything else present as placeholder
    assert bp["financial_projections"] == "(not addressed)"
    assert all(s in bp for s in BLUEPRINT_SECTIONS)


async def test_unparseable_output_degrades_gracefully():
    claude = FakeClaude("the model rambled and produced no JSON")
    result = await synthesize_blueprint("idea", _AGENT_OUTPUTS, claude)
    bp = result["blueprint"]
    # all sections present as placeholders, tokens still counted, no exception
    assert all(bp[s] == "(not addressed)" for s in BLUEPRINT_SECTIONS)
    assert result["tokens_used"] == 321


async def test_prompt_includes_specialist_and_board_context():
    claude = FakeClaude("{}")
    await synthesize_blueprint("my startup idea", _AGENT_OUTPUTS, claude)
    msg = claude.last_user_message
    assert "my startup idea" in msg
    assert "BOARD DEBATE" in msg          # board minutes are fed in
    assert "CEO" in msg and "Research" in msg
