"""Tests for tools (calculator, web search)."""

import pytest
from app.tools.calculator import safe_eval
from app.tools import web_search as web_search_module
from app.tools.web_search import web_search
from app.agents.finance_agent import _amount, _financial_inputs, audit_projections


class TestCalculator:
    """Test the safe math evaluator."""

    def test_basic_addition(self):
        assert safe_eval("2 + 3") == 5.0

    def test_multiplication(self):
        assert safe_eval("1499 * 12") == 17988.0

    def test_percentage_calculation(self):
        result = safe_eval("1499 * 0.37")
        assert abs(result - 554.63) < 0.01

    def test_exponentiation(self):
        assert safe_eval("2 ** 10") == 1024.0

    def test_negative_numbers(self):
        assert safe_eval("-5 + 3") == -2.0

    def test_complex_expression(self):
        result = safe_eval("(100 - 30) * 12 * 500")
        assert result == 420000.0

    def test_division(self):
        assert safe_eval("100 / 4") == 25.0

    def test_division_by_zero(self):
        with pytest.raises(Exception):
            safe_eval("1 / 0")

    def test_rejects_function_calls(self):
        with pytest.raises(ValueError):
            safe_eval("__import__('os').system('ls')")

    def test_rejects_string_literals(self):
        with pytest.raises(ValueError):
            safe_eval("'hello'")

    def test_rejects_attribute_access(self):
        with pytest.raises(ValueError):
            safe_eval("().__class__.__bases__")


@pytest.fixture
def offline_search(monkeypatch):
    """Simulate no reachable live search source (keeps tests off the network)."""
    async def _fail(query, count):
        raise RuntimeError("offline")
    monkeypatch.setattr(web_search_module, "_wikipedia_search", _fail)


@pytest.mark.asyncio
@pytest.mark.usefixtures("offline_search")
class TestWebSearch:
    """Test the web search tool's labelled placeholder fallback."""

    async def test_mock_search_returns_results(self):
        results = await web_search("test query", count=3)
        assert isinstance(results, list)
        assert len(results) > 0

    async def test_mock_search_has_required_fields(self):
        results = await web_search("market size India")
        for result in results:
            assert "title" in result
            assert "url" in result
            assert "description" in result

    async def test_mock_search_includes_query(self):
        results = await web_search("AI startup market")
        # Mock results should reference the query
        combined = " ".join(r["title"] + r["description"] for r in results)
        assert "AI startup market" in combined


@pytest.mark.asyncio
async def test_web_search_uses_wikipedia_without_brave_key(monkeypatch):
    async def _wiki(query, count):
        return [{"title": "HealthifyMe", "url": "https://en.wikipedia.org/wiki/HealthifyMe",
                 "description": "Indian health app", "source": "wikipedia"}]
    monkeypatch.setattr(web_search_module, "_wikipedia_search", _wiki)
    results = await web_search("fitness app India")
    assert results[0]["source"] == "wikipedia"


def test_keywords_strip_question_words_and_jargon():
    assert web_search_module._keywords("What is the TAM for fitness apps in India?") == "fitness apps India"


class TestFinanceCalculator:
    def test_amount_parsing(self):
        assert _amount("₹499/mo") == 499
        assert _amount("$1.2M") == 1_200_000
        assert _amount("₹50,000-₹2,00,000/month") == 125_000

    @pytest.mark.asyncio
    async def test_inputs_use_upstream_pricing_and_costs(self):
        ctx = {
            "marketing_output": {"pricing_strategy": {"starter": "₹299/mo", "pro": "₹799/mo", "trial": "14-day free trial"},
                                 "estimated_monthly_budget": "₹1,00,000/month"},
            "developer_output": {"estimated_monthly_infra_cost": "₹5000/month"},
        }
        calc = await _financial_inputs("", ctx)
        assert calc["average_plan_price"] == 549
        assert calc["monthly_variable_burn"] == 105_000
        assert calc["subscribers_to_cover_marketing_and_infra"] == 192

    def test_audit_corrects_inconsistent_profit(self):
        out = {"revenue_projections": {
            "month_1": {"revenue": 10_000, "costs": 40_000, "profit": -30_000},
            "month_6": {"revenue": 500_000, "costs": 200_000, "profit": 100_000},
        }}
        audit = audit_projections(out)
        assert audit["corrections"] == 1
        assert out["revenue_projections"]["month_6"]["profit"] == 300_000
