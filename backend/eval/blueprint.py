"""Shared blueprint schema + fair rendering for the judge.

Both the baseline and the pipeline are reduced to the SAME canonical section
list before judging, and rendered identically as markdown — so the judge scores
content, not formatting or which system produced it.
"""

import json
from typing import Any, Dict

# The canonical sections a startup blueprint should cover (single source of truth
# lives with the production synthesizer). The baseline fills these directly; the
# pipeline's synthesizer produces them from the specialists' work.
from app.agents.synthesizer import BLUEPRINT_SECTIONS as SECTIONS


def render_markdown(blueprint: Dict[str, Any]) -> str:
    """Render a blueprint dict as readable markdown for the judge."""
    parts = []
    for section in SECTIONS:
        title = section.replace("_", " ").title()
        value = blueprint.get(section, "(missing)")
        parts.append(f"## {title}\n")
        if isinstance(value, (dict, list)):
            parts.append("```json\n" + json.dumps(value, indent=2, ensure_ascii=False) + "\n```")
        else:
            parts.append(str(value))
        parts.append("")
    return "\n".join(parts)
