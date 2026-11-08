"""AgentForge AI — Board Meeting Node

After all 7 agents complete, this node stages a multi-round debate
where agents challenge each other's outputs. The result is a synthesis
that identifies unresolved risks and builds cross-agent consensus.

This is NOT a BaseAgent subclass — it's a standalone LangGraph node function
that runs multiple Claude calls internally to simulate the debate.
"""

import json
from app.json_utils import loads_tolerant
import time
import logging
from typing import Dict, Any

from app.services.claude_service import get_claude_service
from app.services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)

# Which agent challenges which (challenger → target)
DEBATE_PAIRS = [
    ("Finance Agent", "CEO Agent", "Revenue model and unit economics assumptions"),
    ("Developer Agent", "Marketing Agent", "Go-to-market timeline feasibility"),
    ("Research Agent", "Finance Agent", "TAM/SAM market sizing accuracy"),
    ("Operations Agent", "Developer Agent", "Infrastructure and scaling readiness"),
]


async def board_meeting_node(state: dict) -> dict:
    """LangGraph node: runs a multi-round agent debate.

    Round 1 — Challenges: Each debate pair generates a targeted challenge.
    Round 2 — Synthesis: All challenges are synthesized into a board decision.
    
    Streams each round to the frontend via WebSocket.
    """
    workflow_id = state["workflow_id"]
    agent_outputs = state.get("agent_outputs", {})
    claude = get_claude_service()

    await ws_manager.send_agent_started(workflow_id, "Board Meeting")
    await ws_manager.send_agent_thinking(
        workflow_id, "Board Meeting",
        "Convening board meeting — agents will now debate and challenge each other's analyses..."
    )

    all_challenges = []
    total_tokens = 0
    total_cost = 0.0

    # ─── Round 1: Challenges ───
    for i, (challenger, target, focus) in enumerate(DEBATE_PAIRS, 1):
        challenger_key = challenger.lower().replace(" agent", "").strip()
        target_key = target.lower().replace(" agent", "").strip()

        challenger_output = agent_outputs.get(f"{challenger_key}_output", {})
        target_output = agent_outputs.get(f"{target_key}_output", {})

        if not target_output:
            continue

        await ws_manager.send_agent_thinking(
            workflow_id, "Board Meeting",
            f"⚔️ Round {i}: {challenger} challenges {target} on {focus}..."
        )

        challenge_prompt = (
            f"You are {challenger} in a board meeting. You are challenging {target}'s analysis.\n"
            f"Focus area: {focus}\n\n"
            f"{target}'s output:\n{json.dumps(target_output, indent=2)[:2000]}\n\n"
            f"Your own analysis for context:\n{json.dumps(challenger_output, indent=2)[:1500]}\n\n"
            f"Raise exactly 2 specific, data-backed challenges. For each:\n"
            f"1. What is the specific weakness or gap?\n"
            f"2. What evidence from your analysis supports this challenge?\n"
            f"3. What would you recommend instead?\n\n"
            f"Return JSON: {{\"challenges\": [{{\"weakness\": \"...\", \"evidence\": \"...\", \"recommendation\": \"...\"}}]}}"
        )

        try:
            _t0 = time.time()
            result = await claude.generate(
                system_prompt=f"You are {challenger} in a startup board meeting. Be constructive but rigorous.",
                user_message=challenge_prompt,
                agent_name="Board Meeting",
                max_tokens=3000,
            )
            total_tokens += result["tokens_used"]
            total_cost += result["cost"]
            await claude.write_agent_log(
                workflow_id, "Board Meeting",
                tokens=result["tokens_used"], cost=result["cost"],
                latency_ms=int((time.time() - _t0) * 1000), status="success",
                output_preview=str(result.get("content", "")),
            )

            try:
                challenge_data = json.loads(result["content"]) if isinstance(result["content"], str) else result["content"]
            except (json.JSONDecodeError, TypeError):
                # Try to extract JSON
                content = result["content"]
                start = content.find("{")
                end = content.rfind("}") + 1
                if start >= 0 and end > start:
                    challenge_data = loads_tolerant(content[start:end])
                else:
                    challenge_data = {"challenges": [{"weakness": "Could not parse challenge", "evidence": "N/A", "recommendation": "N/A"}]}

            challenges = challenge_data.get("challenges", [])
            for c in challenges:
                c["challenger"] = challenger
                c["target"] = target
                all_challenges.append(c)

            preview = challenges[0].get("weakness", "")[:100] if challenges else "No challenges"
            await ws_manager.send_board_meeting_round(
                workflow_id, i, challenger, target,
                f"{preview}"
            )

        except Exception as e:
            logger.warning(f"Board meeting challenge {challenger} → {target} failed: {e}")
            await ws_manager.send_board_meeting_round(
                workflow_id, i, challenger, target,
                f"Challenge skipped: {str(e)[:80]}"
            )

    # ─── Round 2: Synthesis ───
    await ws_manager.send_agent_thinking(
        workflow_id, "Board Meeting",
        "🤝 Synthesizing all debate points into board decision..."
    )

    synthesis_prompt = (
        f"You are the Board Secretary synthesizing a startup board meeting.\n\n"
        f"Business idea: {state.get('brief', 'N/A')}\n\n"
        f"The following challenges were raised during the debate:\n"
        f"{json.dumps(all_challenges, indent=2)}\n\n"
        f"Produce a board decision with:\n"
        f"1. consensus_score (0-100): How confident is the board in this idea?\n"
        f"2. key_risks_after_debate: Top 3-5 risks that survived the debate\n"
        f"3. revised_recommendations: Top 3-5 actionable recommendations\n"
        f"4. board_decision: A 3-4 sentence executive summary of the board's verdict\n\n"
        f"Return valid JSON matching this schema:\n"
        f'{{"consensus_score": int, "key_risks_after_debate": [str], '
        f'"revised_recommendations": [str], "board_decision": str, '
        f'"debate_points": []}}'
    )

    try:
        _t0 = time.time()
        synthesis_result = await claude.generate(
            system_prompt="You are a neutral board secretary producing a consensus document.",
            user_message=synthesis_prompt,
            agent_name="Board Meeting",
            max_tokens=4096,
        )
        total_tokens += synthesis_result["tokens_used"]
        total_cost += synthesis_result["cost"]
        await claude.write_agent_log(
            workflow_id, "Board Meeting",
            tokens=synthesis_result["tokens_used"], cost=synthesis_result["cost"],
            latency_ms=int((time.time() - _t0) * 1000), status="success",
            output_preview=str(synthesis_result.get("content", "")),
        )

        try:
            board_output = json.loads(synthesis_result["content"])
        except (json.JSONDecodeError, TypeError):
            content = synthesis_result["content"]
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                board_output = loads_tolerant(content[start:end])
            else:
                board_output = {
                    "consensus_score": 60,
                    "key_risks_after_debate": ["Unable to parse synthesis"],
                    "revised_recommendations": [],
                    "board_decision": "Board meeting completed with parsing issues.",
                }

        # Inject the raw debate points
        board_output["debate_points"] = [
            {
                "challenger": c.get("challenger", ""),
                "target": c.get("target", ""),
                "challenge": c.get("weakness", ""),
                "rebuttal": c.get("evidence", ""),
                "resolution": c.get("recommendation", ""),
            }
            for c in all_challenges
        ]

    except Exception as e:
        logger.error(f"Board meeting synthesis failed: {e}")
        board_output = {
            "consensus_score": 50,
            "key_risks_after_debate": [f"Synthesis failed: {str(e)}"],
            "revised_recommendations": [],
            "board_decision": "Board meeting encountered errors during synthesis.",
            "debate_points": [],
        }

    # Validate via Pydantic if available
    try:
        from app.models.agent_outputs import BoardMeetingOutput
        validated = BoardMeetingOutput(**board_output)
        board_output = validated.model_dump()
    except Exception:
        pass

    score = board_output.get("consensus_score", "?")
    risks = len(board_output.get("key_risks_after_debate", []))
    await ws_manager.send_agent_completed(
        workflow_id, "Board Meeting",
        f"Consensus: {score}/100 | {risks} risks identified | {len(all_challenges)} debate points"
    )

    logger.info(f"[LangGraph] Board Meeting completed: {total_tokens} tokens, score={score}")

    return {
        "agent_outputs": {"board_meeting_output": board_output},
        "completed_agents": ["Board Meeting"],
        "total_tokens": total_tokens,
        "total_cost": total_cost,
    }
