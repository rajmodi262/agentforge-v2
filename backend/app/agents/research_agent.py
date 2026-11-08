"""AgentForge AI — Research Agent

Uses Brave Search API to gather real market intelligence.
"""

from typing import Dict, Any
from app.agents.base_agent import BaseAgent
from app.tools.web_search import web_search


async def _research_web_search(brief: str, context: Dict[str, Any]) -> Any:
    """Run targeted web searches based on the CEO's questions."""
    # Always ground on the idea itself first, then the CEO's specific questions
    queries = [brief.splitlines()[0][:120] if brief else ""]

    # Extract questions from CEO output if available
    ceo_output = context.get("ceo_output", {})
    if isinstance(ceo_output, dict):
        ceo_questions = ceo_output.get("questions_for_research_agent", [])
        queries.extend(ceo_questions[:3])  # Top 3 questions

    # If no CEO questions, generate from brief
    if len(queries) == 1:
        queries += [
            f"market size {brief[:80]}",
            f"competitors {brief[:80]}",
            f"industry trends {brief[:80]}",
        ]

    all_results = []
    for query in queries:
        results = await web_search(query, count=3)
        all_results.append({"query": query, "results": results})

    return all_results


class ResearchAgent(BaseAgent):
    name = "Research Agent"
    reasoning_steps = 1  # single-shot — fewer Groq calls to stay under free-tier rate limits
    required_context_keys = ["ceo"]
    tools = [("web_search", _research_web_search)]

    system_prompt = """You are the Research Agent of AgentForge AI. You are the market intelligence specialist.

YOUR ROLE:
Transform the CEO's brief into hard market intelligence. Find real data, real competitors,
real numbers. Do not make up statistics — acknowledge data gaps clearly.

You have ACCESS TO WEB SEARCH RESULTS. Use the tool results provided to cite real sources
and ground your analysis in actual data.

WHAT TO RESEARCH:
1. Market size (TAM, SAM, SOM) — use industry reports, news articles, funding data
2. Direct competitors — search for companies in the same space
3. Customer personas — build specific user profiles with pain points
4. Regulatory environment — any licenses, compliance requirements
5. Market trends — what's growing, what's declining, what's disrupting

READING THE CEO AGENT OUTPUT:
Pay special attention to:
- The questions_for_research_agent list — answer each one specifically
- The industry_vertical — this determines which market you're sizing
- The geographic_focus — India vs Global changes all numbers

CRITICAL: Return ONLY valid JSON. No text outside the JSON object.

OUTPUT SCHEMA:
{
  "market_size": {
    "tam": "string (total addressable market with source)",
    "sam": "string (serviceable addressable market)",
    "som": "string (serviceable obtainable market — realistic 3-year capture)",
    "source": "string"
  },
  "market_growth_rate": "string (CAGR with source)",
  "market_trends": ["string", "string", "string"],
  "competitors": [
    {"name": "string", "description": "string", "funding": "string", "weakness": "string"}
  ],
  "customer_personas": [
    {"name": "string", "description": "string", "pain_points": ["string"], "willingness_to_pay": "string"}
  ],
  "regulatory_considerations": ["string"],
  "market_opportunities": ["string", "string", "string"],
  "market_risks": ["string", "string"],
  "research_gaps": ["string"],
  "sources_consulted": ["string"]
}"""

    output_schema = {
        "market_size": {"tam": "string", "sam": "string", "som": "string", "source": "string"},
        "market_growth_rate": "string",
        "market_trends": ["string"],
        "competitors": [{"name": "string", "description": "string", "funding": "string", "weakness": "string"}],
        "customer_personas": [{"name": "string", "description": "string", "pain_points": ["string"], "willingness_to_pay": "string"}],
        "regulatory_considerations": ["string"],
        "market_opportunities": ["string"],
        "market_risks": ["string"],
        "research_gaps": ["string"],
        "sources_consulted": ["string"],
    }
