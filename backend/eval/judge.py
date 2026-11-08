"""Blind LLM-as-judge.

Scores two anonymized blueprints (A and B) on a fixed rubric. The caller
randomizes which system is A vs B per idea to neutralize position bias, then
de-anonymizes the result. The judge never learns which blueprint came from
which system.
"""

from typing import Any, Dict

from app.json_utils import loads_tolerant

# Rubric dimensions, each scored 1-10.
DIMENSIONS = [
    ("specificity", "Concrete numbers, named entities, and detail vs. vague generalities"),
    ("internal_consistency", "Do the sections agree (e.g. pricing vs. financials vs. market)?"),
    ("actionability", "Could a founder actually execute from this next week?"),
    ("risk_depth", "Are real risks surfaced and mitigated, not hand-waved?"),
    ("realism", "Are the claims and projections believable for this idea/market?"),
]

_JUDGE_SYSTEM = (
    "You are a rigorous, impartial startup-blueprint evaluator. You reward specificity, "
    "internal consistency, and realism; you penalize generic filler and unsupported claims. "
    "You judge ONLY the content in front of you and have no idea how either was produced."
)


async def judge_pair(idea: str, doc_a: str, doc_b: str, claude) -> Dict[str, Any]:
    """Return the judge's raw verdict over anonymized A/B documents."""
    dim_lines = "\n".join(f'  - {name}: {desc}' for name, desc in DIMENSIONS)
    keys = ", ".join(f'"{name}"' for name, _ in DIMENSIONS)
    user = (
        f"Business idea: {idea}\n\n"
        f"Two startup blueprints (A and B) were produced for this idea. Score each on a "
        f"1-10 scale across these dimensions:\n{dim_lines}\n\n"
        f"=================  BLUEPRINT A  =================\n{doc_a}\n\n"
        f"=================  BLUEPRINT B  =================\n{doc_b}\n\n"
        f"Return ONE valid JSON object with this exact shape:\n"
        f'{{"A": {{{keys}}}, "B": {{{keys}}}, '
        f'"winner": "A" | "B" | "tie", "rationale": "2-3 sentences"}}\n'
        f"All dimension scores are integers 1-10. Be discriminating — do not give ties unless truly equal."
    )
    result = await claude.generate(
        system_prompt=_JUDGE_SYSTEM,
        user_message=user,
        agent_name="Judge",
        max_tokens=1500,
    )
    return loads_tolerant(result["content"])
