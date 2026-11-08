"""Tests for orchestrator fan-in reducer + agent JSON parsing."""

import pytest
from app.agents.orchestrator import _merge_dicts
from app.agents.base_agent import BaseAgent


# ─── Fan-in reducer: concurrent agent writes must merge, not clobber ───

def test_merge_combines_distinct_keys():
    assert _merge_dicts({"research_output": 1}, {"finance_output": 2}) == {
        "research_output": 1, "finance_output": 2
    }


def test_merge_new_value_overrides_same_key():
    assert _merge_dicts({"a": 1}, {"a": 2}) == {"a": 2}


def test_merge_is_non_destructive_to_existing():
    existing = {"a": 1}
    _merge_dicts(existing, {"b": 2})
    assert existing == {"a": 1}  # reducer must not mutate the prior state


def test_merge_simulated_parallel_fanin():
    # 4 agents each write their own key into shared state
    state = {}
    for upd in ({"research_output": "r"}, {"marketing_output": "m"},
                {"developer_output": "d"}, {"finance_output": "f"}):
        state = _merge_dicts(state, upd)
    assert set(state) == {"research_output", "marketing_output",
                          "developer_output", "finance_output"}


# ─── Agent JSON parsing across the formats LLMs emit ───

@pytest.fixture
def agent():
    return BaseAgent()


def test_parse_plain_json(agent):
    assert agent._parse_output('{"a": 1}') == {"a": 1}


def test_parse_markdown_fenced(agent):
    assert agent._parse_output('here:\n```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_generic_fence(agent):
    assert agent._parse_output('```\n{"a": 1}\n```') == {"a": 1}


def test_parse_with_surrounding_prose(agent):
    assert agent._parse_output('Sure! {"a": 1} done.') == {"a": 1}


def test_parse_truncated_falls_back_to_tolerant(agent):
    out = agent._parse_output('{"a": 1, "b": "trunc')
    assert out["a"] == 1


def test_parse_garbage_raises(agent):
    with pytest.raises(ValueError):
        agent._parse_output("no json here whatsoever")
