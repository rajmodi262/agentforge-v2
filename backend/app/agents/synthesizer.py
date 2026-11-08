"""AgentForge — Chief Synthesizer (Editor) stage.

The 7 specialist agents produce deep, domain-specific analyses, and the Board
Meeting surfaces cross-functional critiques. But raw, they're disconnected
fragments. This stage is what a real multi-agent system needs: an editor that
weaves the specialists' depth + the debate's critiques into ONE coherent,
specific, internally-consistent blueprint — resolving contradictions and
carrying concrete numbers through.

Used by both the production orchestrator (a real `synthesis` node) and the
evaluation harness, so the eval measures the actual product.
"""

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Canonical blueprint sections — the single source of truth (the eval imports this).
BLUEPRINT_SECTIONS = [
    "vision_and_problem",
    "market_research",
    "go_to_market",
    "technical_architecture",
    "financial_projections",
    "operations_and_hiring",
    "key_risks",
]

_SYNTH_SYSTEM = (
    "You are the Chief Strategy Officer and editor of a startup blueprint. You are handed "
    "detailed analyses from seven specialist agents (CEO, Research, Marketing, Developer, "
    "Finance, Analytics, Operations) and the minutes of a board debate that challenged them. "
    "Your job is to synthesize ALL of it into a single, coherent, investor-ready blueprint.\n\n"
    "QUALITY BAR — write like a top-tier consultant, not a brochure:\n"
    "- Every claim gets a NUMBER and a one-line justification (e.g. 'CAC ~Rs.850, assuming "
    "2.2% conversion on Rs.40 CPC Meta ads' — never just 'low CAC').\n"
    "- Name real, specific competitors, channels, tools and price points; never say "
    "'existing players' or 'various channels'.\n"
    "- PRESERVE the specialists' concrete figures verbatim (TAM/SAM/SOM, pricing tiers, "
    "break-even month, infra cost, hiring plan) — do not round them away into prose.\n"
    "- Resolve contradictions between specialists explicitly ('Finance assumed Rs.499/mo but "
    "Marketing priced Rs.299 — reconciling at Rs.399 because ...').\n"
    "- Include a concrete first-90-days action plan with weekly milestones.\n"
    "- Fold the board's surviving risks in with mitigations, each risk scored high/med/low.\n"
    "- BANNED: 'leverage', 'cutting-edge', 'robust', 'seamless', 'delve', 'in today's "
    "fast-paced world' and any sentence that could apply to every startup."
)


def _trim(value: Any, limit: int = 2600) -> str:
    s = json.dumps(value, ensure_ascii=False)
    return s if len(s) <= limit else s[:limit] + " …[truncated]"


def _build_user_message(brief: str, agent_outputs: Dict[str, Any]) -> str:
    parts = [f"STARTUP IDEA: {brief}", "", "SPECIALIST ANALYSES:"]
    label = {
        "ceo_output": "CEO (framing & strategy)",
        "research_output": "Research (market)",
        "marketing_output": "Marketing (GTM)",
        "developer_output": "Developer (tech)",
        "finance_output": "Finance (projections)",
        "analytics_output": "Analytics (KPIs)",
        "operations_output": "Operations (execution)",
    }
    for key, lab in label.items():
        if agent_outputs.get(key):
            parts.append(f"\n--- {lab} ---\n{_trim(agent_outputs[key])}")
    if agent_outputs.get("board_meeting_output"):
        parts.append(f"\n--- BOARD DEBATE (risks & revised recommendations) ---\n"
                     f"{_trim(agent_outputs['board_meeting_output'], 3200)}")

    section_list = "\n".join(f'  - "{s}"' for s in BLUEPRINT_SECTIONS)
    parts.append(
        "\nSynthesize the above into ONE coherent blueprint. Return a single valid JSON "
        f"object with exactly these top-level keys:\n{section_list}\n"
        "Each value should be a rich object or list. Be specific and concrete (real numbers, "
        "named channels, a real stack), internally consistent across sections, and economical "
        "with words so the JSON stays complete and valid. Reflect the board's critiques in "
        "'key_risks' and wherever they change a recommendation."
    )
    return "\n".join(parts)


async def synthesize_blueprint(
    brief: str,
    agent_outputs: Dict[str, Any],
    claude,
    workflow_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Produce one coherent blueprint (canonical sections) from all agent outputs.

    Returns the blueprint dict; missing sections are filled with a placeholder so
    downstream rendering stays symmetric.
    """
    from app.json_utils import loads_tolerant

    user = _build_user_message(brief, agent_outputs)
    result = await claude.generate(
        system_prompt=_SYNTH_SYSTEM,
        user_message=user,
        agent_name="Chief Synthesizer",
        max_tokens=8192,
    )
    try:
        blueprint = loads_tolerant(result["content"])
        if not isinstance(blueprint, dict):
            raise ValueError("synthesis did not return an object")
    except Exception as e:
        logger.warning(f"Synthesis parse failed ({e}); falling back to raw assembly")
        blueprint = {}

    for s in BLUEPRINT_SECTIONS:
        blueprint.setdefault(s, "(not addressed)")

    return {"blueprint": blueprint, "tokens_used": result.get("tokens_used", 0)}
