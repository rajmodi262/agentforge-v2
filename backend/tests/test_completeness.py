"""Tests for blank-field prevention: strict schemas for local models + gap detection."""

from app.agents.base_agent import BaseAgent
from app.models.agent_outputs import CEOOutput, OperationsOutput
from app.services.claude_service import strict_schema


def test_strict_schema_requires_every_field():
    s = strict_schema(OperationsOutput.model_json_schema())
    assert set(s["required"]) == set(s["properties"])
    assert all("default" not in p for p in s["properties"].values())


def test_strict_schema_forbids_blank_values():
    s = strict_schema(OperationsOutput.model_json_schema())
    assert s["properties"]["immediate_actions"]["minItems"] == 1
    assert s["properties"]["decision_framework"]["minLength"] == 1


def test_strict_schema_drops_null_option():
    prop = strict_schema(CEOOutput.model_json_schema())["properties"]["target_user_secondary"]
    assert all(o.get("type") != "null" for o in prop.get("anyOf", [prop]))


def test_strict_schema_leaves_original_untouched():
    original = OperationsOutput.model_json_schema()
    strict_schema(original)
    assert "minItems" not in original["properties"]["immediate_actions"]


def test_empty_fields_catches_blanks_and_placeholders():
    out = {k: "filled" for k in CEOOutput.model_fields}
    out.update(target_user_secondary="null", key_assumptions=[], top_risks="N/A")
    assert set(BaseAgent._empty_fields(out, CEOOutput)) == {"target_user_secondary", "key_assumptions", "top_risks"}
