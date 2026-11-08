"""Single-prompt baseline: one strong LLM call produces the whole blueprint.

This is deliberately a STRONG baseline (generous tokens, an explicit expert
persona, and the same section list the pipeline covers) so the comparison is
honest. A weak baseline would rig the eval in the pipeline's favour.
"""

from typing import Any, Dict, Tuple

from app.json_utils import loads_tolerant
from eval.blueprint import SECTIONS

_BASELINE_SYSTEM = (
    "You are a senior startup analyst and former VC partner. You write rigorous, "
    "specific, realistic startup blueprints — concrete numbers, named channels, "
    "honest risks. You avoid generic filler."
)


async def generate_baseline(idea: str, claude) -> Tuple[Dict[str, Any], int]:
    """Return (blueprint_dict, tokens_used) for the single-prompt baseline."""
    section_list = "\n".join(f'  - "{s}"' for s in SECTIONS)
    user = (
        f"Business idea: {idea}\n\n"
        f"Produce a complete, investor-ready startup blueprint. Be specific: use real "
        f"numbers (TAM/SAM/SOM, pricing, CAC, runway), named acquisition channels, a "
        f"concrete tech stack, a 3-year financial trajectory, a hiring plan, and the "
        f"sharpest risks with mitigations.\n\n"
        f"Return ONE valid JSON object with exactly these top-level keys, each a rich "
        f"object or list:\n{section_list}\n\n"
        f"Cover every key thoroughly but be economical with words — concise, concrete "
        f"phrases over long prose, so the JSON stays complete and valid."
    )
    result = await claude.generate(
        system_prompt=_BASELINE_SYSTEM,
        user_message=user,
        agent_name="Baseline",
        max_tokens=8192,
    )
    blueprint = loads_tolerant(result["content"])
    # Ensure every canonical section exists so rendering is symmetric with the pipeline
    for s in SECTIONS:
        blueprint.setdefault(s, "(not addressed)")
    return blueprint, result.get("tokens_used", 0)
