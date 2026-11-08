"""AgentForge AI — Finance Agent

Uses the Calculator tool twice:
1. Before the LLM call — derives cost/price anchors (burn rate, break-even
   subscribers) from the Marketing pricing and Developer infra estimates.
2. After the LLM call — audits the projected revenue/costs/profit arithmetic
   and corrects any month where profit != revenue - costs.
"""

import re
from typing import Dict, Any, List, Optional
from app.agents.base_agent import BaseAgent
from app.tools.calculator import safe_eval
from app.services.websocket_manager import ws_manager

_SUFFIXES = {"k": 1e3, "l": 1e5, "lakh": 1e5, "lakhs": 1e5, "m": 1e6, "mn": 1e6, "cr": 1e7, "crore": 1e7}
_NUM_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(crore|lakhs?|cr|mn|k|l|m)?\b", re.IGNORECASE)


def _amount(value: Any) -> Optional[float]:
    """Parse a money-ish value ("₹499/mo", "$1.2M", "50k-2L") into a number (mean of a range)."""
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    nums = []
    for raw, suffix in _NUM_RE.findall(value):
        n = float(raw.replace(",", ""))
        if suffix:
            n *= _SUFFIXES.get(suffix.lower(), 1)
        nums.append(n)
    return sum(nums) / len(nums) if nums else None


def _plan_prices(pricing: Any) -> List[float]:
    """Pull per-plan prices out of the Marketing agent's pricing_strategy."""
    prices = []
    if isinstance(pricing, dict):
        for name, desc in pricing.items():
            if "trial" in str(name).lower():
                continue
            amt = _amount(desc)
            if amt and amt > 0:
                prices.append(amt)
    return prices


async def _financial_inputs(brief: str, context: Dict[str, Any]) -> Any:
    """Calculator tool: derive cost and pricing anchors from upstream agents."""
    marketing = context.get("marketing_output") or {}
    developer = context.get("developer_output") or {}
    if not isinstance(marketing, dict):
        marketing = {}
    if not isinstance(developer, dict):
        developer = {}

    prices = _plan_prices(marketing.get("pricing_strategy"))
    marketing_budget = _amount(marketing.get("estimated_monthly_budget"))
    infra_cost = _amount(developer.get("estimated_monthly_infra_cost"))

    calcs: Dict[str, Any] = {"tool": "calculator", "inputs": {
        "plan_prices": prices,
        "monthly_marketing_budget": marketing_budget,
        "monthly_infra_cost": infra_cost,
    }}
    if prices:
        expr = f"({' + '.join(str(p) for p in prices)}) / {len(prices)}"
        calcs["average_plan_price"] = round(safe_eval(expr), 2)
        calcs["average_plan_price_formula"] = expr
    if marketing_budget is not None and infra_cost is not None:
        expr = f"{marketing_budget} + {infra_cost}"
        calcs["monthly_variable_burn"] = round(safe_eval(expr), 2)
        calcs["monthly_variable_burn_formula"] = expr
        if prices:
            be = f"{calcs['monthly_variable_burn']} / {calcs['average_plan_price']}"
            calcs["subscribers_to_cover_marketing_and_infra"] = int(safe_eval(be)) + 1
            calcs["subscribers_formula"] = be
    if len(calcs) == 2:
        calcs["note"] = "Upstream agents gave no parseable pricing/cost figures — estimate from the brief."
    return calcs


def audit_projections(output: Dict[str, Any]) -> Dict[str, Any]:
    """Calculator tool: verify profit = revenue - costs for every projected month.

    Corrects inconsistent months in place and returns an audit record.
    """
    checks, corrections = [], 0
    projections = output.get("revenue_projections")
    if not isinstance(projections, dict):
        return {"tool": "calculator", "checks": [], "corrections": 0}
    for month, row in projections.items():
        if not isinstance(row, dict):
            continue
        try:
            revenue = float(row.get("revenue") or 0)
            costs = float(row.get("costs") or 0)
        except (TypeError, ValueError):
            continue
        expected = safe_eval(f"{revenue} - {costs}")
        reported = row.get("profit")
        ok = isinstance(reported, (int, float)) and abs(float(reported) - expected) <= max(1.0, abs(expected) * 0.01)
        margin = round(safe_eval(f"({revenue} - {costs}) / {revenue} * 100"), 1) if revenue else None
        if not ok:
            row["profit"] = expected
            corrections += 1
        checks.append({
            "month": month,
            "formula": f"{revenue:g} - {costs:g}",
            "profit": expected,
            "reported_profit": reported,
            "consistent": ok,
            "net_margin_pct": margin,
        })
    return {"tool": "calculator", "checks": checks, "corrections": corrections}


class FinanceAgent(BaseAgent):
    name = "Finance Agent"
    reasoning_steps = 1  # single-shot — fewer Groq calls to stay under free-tier rate limits
    required_context_keys = ["ceo", "research", "marketing", "developer"]
    tools = [("financial_calculator", _financial_inputs)]

    system_prompt = """You are the Finance Agent of AgentForge AI. You are a startup CFO who has managed
finances for 3 funded startups from pre-seed to Series A.

YOUR ROLE:
Build complete financial projections using data from all previous agents.

READING PREVIOUS AGENT OUTPUTS:
- CEO Agent: use revenue_model and stage_assumption for financial framing
- Research Agent: use market_size for TAM-based revenue ceiling
- Marketing Agent: use pricing_strategy and estimated_monthly_budget for cost modeling
- Developer Agent: use estimated_monthly_infra_cost for tech burn rate

You have ACCESS TO CALCULATOR TOOL RESULTS (average plan price, monthly burn, subscribers
needed to cover it) — anchor your numbers to them. profit MUST equal revenue - costs:
a calculator audits every projected month after you answer.

YOUR DELIVERABLES:
1. Revenue projections (Month 1, 6, 12, 36) with subscriber/customer counts
2. Unit economics (ARPU, cost per unit, gross margin, CAC, LTV, LTV/CAC)
3. Break-even analysis (fixed costs, contribution margin, months to break-even)
4. Funding recommendation
5. Key financial risks with mitigations

CRITICAL: Return ONLY valid JSON. No text outside the JSON object.

OUTPUT SCHEMA:
{
  "revenue_projections": {
    "month_1": {"subscribers": number, "revenue": number, "costs": number, "profit": number},
    "month_6": {"subscribers": number, "revenue": number, "costs": number, "profit": number},
    "month_12": {"subscribers": number, "revenue": number, "costs": number, "profit": number},
    "month_36": {"subscribers": number, "revenue": number, "costs": number, "profit": number}
  },
  "unit_economics": {
    "average_revenue_per_user": "string",
    "cost_per_unit": "string",
    "gross_margin": "string",
    "customer_acquisition_cost": "string",
    "lifetime_value": "string",
    "ltv_cac_ratio": "string"
  },
  "break_even_analysis": {
    "monthly_fixed_costs": "string",
    "contribution_margin_per_subscriber": "string",
    "break_even_subscribers": number,
    "expected_break_even_month": "string"
  },
  "funding_recommendation": "string",
  "key_financial_risks": ["string"]
}"""

    output_schema = {
        "revenue_projections": {
            "month_1": {"subscribers": 0, "revenue": 0, "costs": 0, "profit": 0},
            "month_6": {"subscribers": 0, "revenue": 0, "costs": 0, "profit": 0},
            "month_12": {"subscribers": 0, "revenue": 0, "costs": 0, "profit": 0},
            "month_36": {"subscribers": 0, "revenue": 0, "costs": 0, "profit": 0},
        },
        "unit_economics": {},
        "break_even_analysis": {},
        "funding_recommendation": "string",
        "key_financial_risks": ["string"],
    }

    async def run(self, brief: str, context: Dict[str, Any], workflow_id: Optional[str] = None) -> Dict[str, Any]:
        result = await super().run(brief, context, workflow_id)
        output = result.get("output")
        if isinstance(output, dict):
            if workflow_id:
                await ws_manager.send_agent_tool_call(
                    workflow_id, self.name, "financial_calculator",
                    "Auditing projections: profit = revenue - costs for each month",
                )
            audit = audit_projections(output)
            output["calculator_audit"] = audit
            if workflow_id:
                await ws_manager.send_agent_thinking(
                    workflow_id, self.name,
                    f"Calculator audit: {len(audit['checks'])} months checked, "
                    f"{audit['corrections']} corrected",
                )
        return result
