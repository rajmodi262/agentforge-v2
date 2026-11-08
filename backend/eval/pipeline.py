"""Run the real 7-agent pipeline (+ Board Meeting) for the eval.

Drives the actual agent classes used in production, but bypasses the DB and
WebSocket layers (workflow_id=None makes those calls no-ops). This is the SAME
reasoning the LangGraph orchestrator performs — just without persistence — so
the eval measures the real product, not a re-implementation.
"""

from typing import Any, Dict, Tuple

from app.agents.ceo_agent import CEOAgent
from app.agents.research_agent import ResearchAgent
from app.agents.marketing_agent import MarketingAgent
from app.agents.developer_agent import DeveloperAgent
from app.agents.finance_agent import FinanceAgent
from app.agents.analytics_agent import AnalyticsAgent
from app.agents.operations_agent import OperationsAgent
from app.agents.board_meeting import board_meeting_node
from app.agents.synthesizer import synthesize_blueprint
from app.services.claude_service import get_claude_service

# Sequential order mirrors the orchestrator's dependency graph (the parallel
# agents are run in series here to stay gentle on free-tier rate limits — the
# cross-referencing value comes from shared context, not wall-clock parallelism).
PIPELINE = [
    ("ceo", CEOAgent),
    ("research", ResearchAgent),
    ("marketing", MarketingAgent),
    ("developer", DeveloperAgent),
    ("finance", FinanceAgent),
    ("analytics", AnalyticsAgent),
    ("operations", OperationsAgent),
]


async def run_pipeline(idea: str) -> Tuple[Dict[str, Any], Dict[str, Any], int]:
    """Run all agents + board + synthesis.

    Returns (final_blueprint, agent_outputs, total_tokens). The final_blueprint is
    the Chief Synthesizer's coherent output — the real pipeline deliverable.
    """
    agent_outputs: Dict[str, Any] = {}
    total_tokens = 0

    for key, AgentClass in PIPELINE:
        agent = AgentClass()
        context = {"brief": idea, **agent_outputs}
        # Resilient per-agent (mirrors the orchestrator): a single agent failing
        # records an error for its section but doesn't sink the whole blueprint.
        try:
            result = await agent.run(brief=idea, context=context, workflow_id=None)
            agent_outputs[f"{key}_output"] = result["output"]
            total_tokens += result.get("tokens_used", 0)
        except Exception as e:
            agent_outputs[f"{key}_output"] = {"error": str(e)}

    # Board Meeting debate — standalone LangGraph node. workflow_id=None keeps its
    # WebSocket/DB writes as no-ops.
    board_state = {"workflow_id": None, "brief": idea, "agent_outputs": agent_outputs}
    board_result = await board_meeting_node(board_state)
    agent_outputs.update(board_result.get("agent_outputs", {}))
    total_tokens += board_result.get("total_tokens", 0)

    # Synthesis / editor stage — the coherent blueprint that is the real deliverable.
    synth = await synthesize_blueprint(idea, agent_outputs, get_claude_service())
    total_tokens += synth.get("tokens_used", 0)

    return synth["blueprint"], agent_outputs, total_tokens
