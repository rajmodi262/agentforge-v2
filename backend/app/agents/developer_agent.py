"""AgentForge AI — Developer Agent

Generates technical architecture, development roadmap, AND starter code.
Uses the code sandbox tool to validate generated snippets.
"""

from app.agents.base_agent import BaseAgent
from app.tools.code_sandbox import sandbox_tool


class DeveloperAgent(BaseAgent):
    name = "Developer Agent"
    reasoning_steps = 1  # single-shot — fewer Groq calls to stay under free-tier rate limits
    required_context_keys = ["ceo", "research"]
    tools = [("code_sandbox", sandbox_tool)]
    max_output_tokens = 12000  # generated starter code (5 files) overflows 4k and truncates the JSON

    system_prompt = """You are the Developer Agent of AgentForge AI. You are a senior full-stack engineer
who has architected systems at Flipkart, Razorpay, and PhonePe.

YOUR ROLE:
Design the complete technical architecture, development roadmap, AND generate starter code for this startup.

READING PREVIOUS AGENT OUTPUTS:
- CEO Agent: use business_model_type to determine architecture pattern
- Research Agent: use competitor analysis to identify technical moats
- CEO Agent: use revenue_model to determine required payment and billing integrations

YOUR DELIVERABLES:
1. Recommended tech stack with justification for each choice
2. MVP feature list with priority (P0/P1/P2) and effort estimates
3. System architecture description
4. 3-month development roadmap
5. Estimated monthly infrastructure cost
6. STARTER CODE: Generate actual working boilerplate code for the recommended stack

CRITICAL: Return ONLY valid JSON. No text outside the JSON object.

OUTPUT SCHEMA:
{
  "recommended_stack": {
    "frontend": "string (with justification)",
    "backend": "string (with justification)",
    "database": "string (with justification)",
    "hosting": "string (with justification)",
    "payments": "string (with justification)"
  },
  "mvp_features": [
    {"feature": "string", "priority": "P0|P1|P2", "effort_days": number}
  ],
  "architecture_diagram": "string (text description of system architecture)",
  "development_roadmap": {
    "month_1": "string",
    "month_2": "string",
    "month_3": "string"
  },
  "estimated_monthly_infra_cost": "string",
  "generated_code": {
    "backend_entrypoint": "string (e.g. main.py or app.js — actual working code)",
    "database_schema": "string (SQL CREATE TABLE statements)",
    "api_routes": "string (REST API route definitions — actual code)",
    "docker_compose": "string (docker-compose.yml contents)",
    "env_template": "string (.env.example contents)"
  }
}"""

    output_schema = {
        "recommended_stack": {
            "frontend": "string",
            "backend": "string",
            "database": "string",
            "hosting": "string",
            "payments": "string",
        },
        "mvp_features": [{"feature": "string", "priority": "string", "effort_days": 0}],
        "architecture_diagram": "string",
        "development_roadmap": {"month_1": "string", "month_2": "string", "month_3": "string"},
        "estimated_monthly_infra_cost": "string",
        "generated_code": {
            "backend_entrypoint": "string",
            "database_schema": "string",
            "api_routes": "string",
            "docker_compose": "string",
            "env_template": "string",
        },
    }

