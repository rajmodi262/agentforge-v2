"""Tests for the tolerant JSON loader (repairs truncated LLM output)."""

import pytest
from app.json_utils import loads_tolerant


def test_plain_valid_json():
    assert loads_tolerant('{"a": 1, "b": "two"}') == {"a": 1, "b": "two"}


def test_markdown_fenced_json():
    content = 'Sure!\n```json\n{"x": [1, 2, 3]}\n```\nhope that helps'
    assert loads_tolerant(content) == {"x": [1, 2, 3]}


def test_already_decoded_passthrough():
    # tool_use inputs arrive as dicts, not strings
    obj = {"already": "parsed"}
    assert loads_tolerant(obj) is obj


def test_truncated_unterminated_string():
    # cut off mid-string — should recover the keys that completed
    out = loads_tolerant('{"a": 1, "b": "hello wor')
    assert out["a"] == 1
    assert "a" in out


def test_truncated_array():
    out = loads_tolerant('{"items": [1, 2, 3')
    assert out["items"][:3] == [1, 2, 3]


def test_truncated_nested_object_drops_incomplete_tail():
    # first section complete, second cut off — keep the complete one
    out = loads_tolerant('{"market": {"tam": "5B"}, "tech": {"stack": "Fast')
    assert out["market"] == {"tam": "5B"}


def test_real_world_long_truncation_recovers_most_keys():
    body = ", ".join(f'"k{i}": "value {i}"' for i in range(20))
    # drop the closing brace and part of the last value
    truncated = "{" + body[:-5]
    out = loads_tolerant(truncated)
    assert isinstance(out, dict)
    assert out["k0"] == "value 0"
    assert len(out) >= 15  # recovered the bulk


def test_unrecoverable_raises():
    with pytest.raises(ValueError):
        loads_tolerant("this is not json at all, no braces")


def test_none_raises():
    with pytest.raises(ValueError):
        loads_tolerant(None)
