"""AgentForge AI — Workflow Graph Visualization API

Exposes the LangGraph topology as a JSON structure for frontend rendering.
Also provides a simple ASCII visualization for debugging.
"""

from fastapi import APIRouter
from typing import List, Dict, Any

router = APIRouter(prefix="/workflow", tags=["Workflow Graph"])

# Graph topology (matches the LangGraph StateGraph in orchestrator.py)
GRAPH_NODES = [
    {"id": "ceo", "label": "CEO Agent", "description": "Vision, business model, revenue strategy", "color": "#e94560", "icon": "👔"},
    {"id": "research", "label": "Research Agent", "description": "Market analysis, competitor intelligence", "color": "#0f3460", "icon": "🔍"},
    {"id": "marketing", "label": "Marketing Agent", "description": "GTM strategy, channels, pricing", "color": "#533483", "icon": "📢"},
    {"id": "developer", "label": "Developer Agent", "description": "Tech stack, architecture, roadmap", "color": "#16213e", "icon": "💻"},
    {"id": "finance", "label": "Finance Agent", "description": "Revenue projections, burn rate, runway", "color": "#e94560", "icon": "💰"},
    {"id": "analytics", "label": "Analytics Agent", "description": "KPIs, metrics framework, dashboards", "color": "#0f3460", "icon": "📊"},
    {"id": "operations", "label": "Operations Agent", "description": "Hiring plan, legal, compliance", "color": "#533483", "icon": "⚙️"},
    {"id": "board_meeting", "label": "Board Meeting", "description": "Agents debate and challenge each other's assumptions", "color": "#e94560", "icon": "🏛️"},
    {"id": "synthesis", "label": "Chief Synthesizer", "description": "Merges all outputs + debate into one blueprint", "color": "#0f3460", "icon": "🧠"},
    {"id": "report", "label": "Report Compiler", "description": "Aggregates all outputs into PDF", "color": "#16213e", "icon": "📄"},
]

GRAPH_EDGES = [
    {"from": "__start__", "to": "ceo", "label": "Initialize"},
    {"from": "ceo", "to": "research", "label": "Vision → Market Analysis"},
    {"from": "research", "to": "marketing", "label": "Research → GTM Strategy (parallel)"},
    {"from": "research", "to": "developer", "label": "Research → Tech Architecture (parallel)"},
    {"from": "marketing", "to": "finance", "label": "Pricing → Financials (fan-in)"},
    {"from": "developer", "to": "finance", "label": "Infra Costs → Financials (fan-in)"},
    {"from": "finance", "to": "analytics", "label": "Financials → KPI Framework"},
    {"from": "analytics", "to": "operations", "label": "KPIs → Operations Plan"},
    {"from": "operations", "to": "board_meeting", "label": "All Outputs → Debate"},
    {"from": "board_meeting", "to": "synthesis", "label": "Debate → Synthesis"},
    {"from": "synthesis", "to": "report", "label": "Blueprint → PDF"},
    {"from": "report", "to": "__end__", "label": "Complete"},
]


@router.get("/graph")
async def get_workflow_graph() -> Dict[str, Any]:
    """Return the full LangGraph workflow topology.
    
    Used by the frontend to render an interactive graph visualization
    showing all agent nodes, their connections, and data flow.
    """
    return {
        "engine": "LangGraph",
        "version": "1.1.10",
        "graph_type": "StateGraph",
        "state_schema": "WorkflowState",
        "topology": "dependency-ordered DAG with parallel fan-out/fan-in",
        "nodes": GRAPH_NODES,
        "edges": GRAPH_EDGES,
        "metadata": {
            "total_agents": len([n for n in GRAPH_NODES if n["id"] not in ("report", "board_meeting", "synthesis")]),
            "total_nodes": len(GRAPH_NODES),
            "total_edges": len(GRAPH_EDGES),
            "supports_conditional_routing": False,
            "supports_human_in_the_loop": False,
            "supports_parallel_execution": True,
        },
    }


@router.get("/graph/mermaid")
async def get_workflow_mermaid() -> Dict[str, str]:
    """Return a Mermaid.js diagram of the workflow graph.
    
    Can be rendered directly in markdown or the frontend.
    """
    lines = ["graph LR"]
    lines.append('    S["🚀 START"] --> CEO["👔 CEO Agent"]')
    lines.append('    CEO --> RES["🔍 Research Agent"]')
    lines.append('    RES --> MKT["📢 Marketing Agent"]')
    lines.append('    RES --> DEV["💻 Developer Agent"]')
    lines.append('    MKT --> FIN["💰 Finance Agent"]')
    lines.append('    DEV --> FIN')
    lines.append('    FIN --> ANA["📊 Analytics Agent"]')
    lines.append('    ANA --> OPS["⚙️ Operations Agent"]')
    lines.append('    OPS --> BRD["🏛️ Board Meeting"]')
    lines.append('    BRD --> SYN["🧠 Chief Synthesizer"]')
    lines.append('    SYN --> RPT["📄 Report Compiler"]')
    lines.append('    RPT --> E["✅ END"]')
    lines.append("")
    lines.append("    style S fill:#1a1a2e,color:#fff")
    lines.append("    style E fill:#1a1a2e,color:#fff")
    lines.append("    style CEO fill:#e94560,color:#fff")
    lines.append("    style RES fill:#0f3460,color:#fff")
    lines.append("    style MKT fill:#533483,color:#fff")
    lines.append("    style DEV fill:#16213e,color:#fff")
    lines.append("    style FIN fill:#e94560,color:#fff")
    lines.append("    style ANA fill:#0f3460,color:#fff")
    lines.append("    style OPS fill:#533483,color:#fff")
    lines.append("    style RPT fill:#16213e,color:#fff")

    return {"mermaid": "\n".join(lines)}


@router.get("/graph/nodes")
async def get_graph_nodes() -> List[Dict[str, Any]]:
    """Return only the nodes (agents) with their metadata."""
    return GRAPH_NODES


@router.get("/graph/edges")
async def get_graph_edges() -> List[Dict[str, Any]]:
    """Return only the edges (data flow) with labels."""
    return GRAPH_EDGES
