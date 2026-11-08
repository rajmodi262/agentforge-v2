"""AgentForge AI — AI Service (Claude + Gemini with Dynamic Mock Fallback)

Supports Claude (Anthropic) and Gemini (Google) as AI providers.
Auto-selects the best available provider based on configured API keys.
Falls back to intelligent mock mode when no keys are available.
"""

import json
import time
import random
import hashlib
import logging
import asyncio
from typing import Optional
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Groq's free tier counts max_tokens against an 8k tokens-per-minute budget, so a
# large output budget (e.g. the Developer agent's 12k) is rejected with a 413.
GROQ_MAX_OUTPUT_TOKENS = 4096

def strict_schema(schema: dict) -> dict:
    """Copy of a Pydantic JSON schema where nothing may be left blank.

    Every property becomes required, strings need ≥1 char, arrays ≥1 item and
    free-form objects ≥1 key. Under constrained decoding this stops small local
    models from answering optional fields with "" / [] / {}.
    """
    import copy

    def walk(node):
        if isinstance(node, dict):
            # Optional[X] → anyOf [X, null]: drop the null branch so "no answer" isn't an option
            opts = node.get("anyOf")
            if isinstance(opts, list) and len(opts) > 1:
                kept = [o for o in opts if o.get("type") != "null"]
                if kept and len(kept) < len(opts):
                    node["anyOf"] = kept
            props = node.get("properties")
            if isinstance(props, dict):
                node["required"] = list(props)
                for p in props.values():
                    p.pop("default", None)
            t = node.get("type")
            if t == "string":
                node.setdefault("minLength", 1)
            elif t == "array":
                node.setdefault("minItems", 1)
            elif t == "object" and not props:
                node.setdefault("minProperties", 1)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        return node

    return walk(copy.deepcopy(schema))


_ollama_probe = {"ok": False, "at": 0.0}


def _ollama_reachable() -> bool:
    """Is a local Ollama server answering? Cached for 30 s so the chain stays cheap."""
    if not settings.ollama_base_url:
        return False
    now = time.monotonic()
    if now - _ollama_probe["at"] < 30:
        return _ollama_probe["ok"]
    try:
        import httpx
        ok = httpx.get(f"{settings.ollama_base_url}/api/version", timeout=1.5).status_code == 200
    except Exception:
        ok = False
    _ollama_probe.update(ok=ok, at=now)
    return ok


# ─────────────────────────────── Keywords & Mock Helpers ───────────────────────────────

def _extract_keywords(text: str) -> list:
    """Extract meaningful keywords from business idea text."""
    stop_words = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "shall",
        "should", "may", "might", "must", "can", "could", "i", "we", "you",
        "they", "he", "she", "it", "my", "your", "our", "their", "this",
        "that", "these", "those", "and", "or", "but", "if", "in", "on",
        "at", "to", "for", "of", "with", "by", "from", "as", "into",
        "through", "about", "between", "want", "need", "like", "make",
        "create", "build", "app", "platform", "service", "product",
    }
    words = text.lower().split()
    keywords = [w.strip(".,!?:;\"'()[]{}") for w in words if len(w) > 2 and w.lower() not in stop_words]
    return keywords[:10]


def _generate_startup_name(keywords: list) -> str:
    """Generate a plausible startup name from keywords."""
    suffixes = ["ly", "ify", "hub", "stack", "labs", "base", "flow", "sync", "nest", "hive", "spot"]
    if keywords:
        base = keywords[0].capitalize()
        suffix = random.choice(suffixes)
        return f"{base}{suffix}"
    return "LaunchPad"


def _seed_random(text: str):
    """Seed random based on input for consistent but varied results."""
    seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
    random.seed(seed)


def _generate_dynamic_mock(agent_name: str, user_message: str) -> dict:
    """Generate input-aware mock responses based on the user's business idea."""
    _seed_random(user_message + agent_name)
    keywords = _extract_keywords(user_message)
    industry = keywords[0].capitalize() if keywords else "Technology"
    industry2 = keywords[1].capitalize() if len(keywords) > 1 else "Digital"
    startup_name = _generate_startup_name(keywords)
    
    target_market = "India"
    for market_kw in ["india", "us", "global", "europe", "asia", "africa", "usa", "uk"]:
        if market_kw in user_message.lower():
            target_market = market_kw.capitalize()
            break

    tam = random.randint(2, 15)
    sam = round(tam * random.uniform(0.05, 0.15), 1)
    som = round(sam * random.uniform(0.005, 0.02), 2)
    cagr = random.randint(18, 35)
    price_low = random.choice([29, 49, 79, 99, 149, 199])
    price_high = price_low * random.choice([2, 3, 4])
    break_even_month = random.randint(8, 18)

    responses = {
        "CEO Agent": {
            "startup_name_suggestion": startup_name,
            "problem_statement": f"The {industry.lower()} space faces critical inefficiencies — existing solutions are fragmented, overpriced, and fail to serve the core user need.",
            "solution_description": f"{startup_name} is an AI-powered {industry.lower()} platform that automates key workflows and delivers 10x better outcomes at a fraction of the cost.",
            "target_user_primary": f"Professionals and small businesses in {target_market} working in the {industry.lower()} sector, ages 25-45",
            "target_user_secondary": "Enterprise clients",
            "business_model_type": random.choice(["B2B SaaS", "B2C", "B2B2C", "Marketplace", "D2C"]),
            "revenue_model": f"Monthly subscription with tiered pricing (₹{price_low}-₹{price_high}/month)",
            "geographic_focus": f"{target_market} — starting with tier-1 cities",
            "industry_vertical": f"{industry} / {industry2}",
            "stage_assumption": "Pre-seed",
            "key_assumptions": ["Market is ready for AI", "Users will pay for efficiency", "CAC can be kept low"],
            "top_risks": ["Competition from incumbents", "Regulatory changes", "High initial churn"],
            "questions_for_research_agent": ["What is the exact TAM in tier-1 cities?", "Who are the direct competitors?"],
            "questions_for_marketing_agent": ["What is the most effective acquisition channel?", "How do we position against legacy players?"],
            "questions_for_developer_agent": ["Can we build this in 8 weeks?", "What is the optimal tech stack?"],
            "questions_for_finance_agent": ["When will we break even?", "How much funding do we need?"],
            "executive_brief": f"{startup_name} targets the ${tam}B {industry.lower()} market in {target_market}."
        },
        "Research Agent": {
            "market_size": {"tam": f"${tam}B", "sam": f"${sam}B", "som": f"${som}B", "source": "Industry Reports 2024"},
            "market_growth_rate": f"{cagr}% CAGR (2023-2028)",
            "market_trends": [f"AI adoption in {industry.lower()}", f"Shift to cloud-native {industry.lower()} platforms"],
            "competitors": [{"name": f"LegacyCorp {industry}", "description": "Incumbent player", "funding": "Series C, $50M", "weakness": "Outdated UI, expensive"}],
            "customer_personas": [{"name": "Tech-savvy Manager", "description": "Mid-level manager looking for efficiency", "pain_points": ["Manual workflows", "Data silos"], "willingness_to_pay": f"₹{price_high}/month"}],
            "regulatory_considerations": ["Data privacy laws (DPDP Act)", "Industry-specific compliance"],
            "market_opportunities": ["Underserved tier-2 markets", "AI-driven personalization"],
            "market_risks": ["Price sensitivity", "Low switching costs"],
            "research_gaps": ["Detailed churn data of competitors", "Exact LTV across different cohorts"],
            "sources_consulted": ["Gartner Reports", "Industry Whitepapers", "Public Financials"],
        },
        "Marketing Agent": {
            "brand_name": startup_name,
            "brand_tagline": f"Smart {industry}. Simplified.",
            "brand_personality": "Modern, trustworthy, innovative",
            "positioning_statement": f"For {industry.lower()} professionals, {startup_name} delivers AI-powered automation at ₹{price_low}/month.",
            "target_channels": [{"channel": "LinkedIn Ads", "strategy": "Target mid-level managers", "expected_cac": "₹1500"}, {"channel": "Content SEO", "strategy": "Industry specific guides", "expected_cac": "₹300"}],
            "launch_strategy": {"phase_1": "Waitlist & Beta", "phase_2": "Public Launch", "phase_3": "Growth & Scale"},
            "pricing_strategy": {"starter_plan": f"₹{price_low}/mo", "popular_plan": f"₹{price_high}/mo", "trial": "14-day free trial"},
            "viral_mechanics": ["Referral discounts", "Watermarked free tier"],
            "estimated_monthly_budget": f"₹{random.randint(50000, 200000)}/month"
        },
        "Developer Agent": {
            "recommended_stack": {"frontend": "React/Next.js", "backend": "Python FastAPI", "database": "PostgreSQL + Redis", "hosting": "AWS / Vercel", "payments": "Stripe / Razorpay"},
            "mvp_features": [{"feature": f"Core {industry.lower()} workflow", "priority": "P0", "effort_days": 8}],
            "architecture_diagram": f"Client -> Load Balancer -> {startup_name} API -> Database",
            "development_roadmap": {"month_1": "Core API and Auth", "month_2": "Frontend Integration", "month_3": "Beta testing and bug fixes"},
            "estimated_monthly_infra_cost": f"₹{random.choice([2000, 5000])}/month",
            "generated_code": {"backend_entrypoint": "from fastapi import FastAPI...", "database_schema": "CREATE TABLE users...", "api_routes": "@app.get('/api')...", "docker_compose": "version: '3'...", "env_template": "DB_URL=..."}
        },
        "Finance Agent": {
            "revenue_projections": {
                "month_1": {"subscribers": random.randint(10, 50), "revenue": random.randint(10000, 50000), "costs": 40000, "profit": -30000},
                "month_6": {"subscribers": random.randint(300, 800), "revenue": random.randint(300000, 800000), "costs": 200000, "profit": 100000},
                "month_12": {"subscribers": random.randint(1000, 2000), "revenue": random.randint(1000000, 2000000), "costs": 500000, "profit": 500000},
                "month_36": {"subscribers": random.randint(5000, 10000), "revenue": random.randint(5000000, 10000000), "costs": 1500000, "profit": 3500000}
            },
            "unit_economics": {"gross_margin": f"{random.randint(60, 80)}%", "ltv_cac_ratio": f"{random.randint(8, 25)}:1", "average_revenue_per_user": f"₹{price_low}", "cost_per_unit": "₹50"},
            "break_even_analysis": {"expected_break_even_month": f"Month {break_even_month}", "monthly_fixed_costs": "₹200000", "break_even_subscribers": 500},
            "funding_recommendation": f"Raise ${random.choice(['500k', '1M'])} Pre-seed",
            "key_financial_risks": ["Higher CAC than expected", "Delayed monetization"]
        },
        "Analytics Agent": {
            "core_kpis": [{"kpi": "MAU", "target": "85% of subscribers", "measurement": "Mixpanel"}],
            "tracking_plan": {"events": ["Sign Up", "Core Action", "Upgrade"], "tools": ["Mixpanel", "Google Analytics", "Sentry"]},
            "growth_metrics": {"north_star_metric": f"Weekly active {industry.lower()} workflows completed", "leading_indicators": ["Daily logins", "Feature usage"], "lagging_indicators": ["Churn rate", "MRR"]},
            "dashboard_recommendations": ["User retention cohort analysis", "Real-time funnel conversion"]
        },
        "Operations Agent": {
            "week_1_to_4_checklist": [{"week": 1, "tasks": [f"Register domain {startup_name.lower()}.com", "Set up cloud infrastructure"]}, {"week": 2, "tasks": ["Launch landing page"]}, {"week": 3, "tasks": ["Beta testing"]}, {"week": 4, "tasks": ["Public launch"]}],
            "hiring_plan": {"month_1": ["1 Full-stack Developer", "1 Designer (part-time)"], "month_3": ["1 Marketing Lead", "1 Customer Success Agent"], "month_6": ["2 Sales Reps", "1 Data Analyst"]},
            "process_documentation": {"daily_ops": "Daily standups, weekly sprint planning", "quality_control": "Code reviews, automated testing", "customer_support": "ZenDesk SLA within 2 hours"},
            "immediate_actions": [f"Register domain {startup_name.lower()}.com", "Set up cloud infrastructure"],
            "legal_checklist": ["Incorporate company", "Draft Terms of Service", "File for trademarks"],
            "tools_stack": [{"tool": "Notion", "purpose": "Documentation", "cost": "$10/mo"}, {"tool": "Slack", "purpose": "Communication", "cost": "$8/mo"}],
            "decision_framework": "Data-driven, customer-centric",
            "success_criteria_90_days": [f"{random.randint(300, 800)}+ active subscribers", "< 10% monthly churn"]
        },
        "Board Meeting": {
            "debate_points": [
                {"challenger": "Finance Agent", "target": "Marketing Agent", "challenge": "CAC expectation is too low for this B2B segment.", "rebuttal": "We will leverage organic SEO to offset paid CAC.", "resolution": "Agreed to blend paid and organic channels to maintain target CAC."}
            ],
            "consensus_score": random.randint(75, 95),
            "key_risks_after_debate": ["Execution speed against incumbents", "Regulatory compliance in data handling"],
            "revised_recommendations": ["Prioritize SOC2 compliance early", "Focus on a niche tier-2 market before expanding"],
            "board_decision": f"The board approves the strategic direction for {startup_name} with a focus on sustainable growth and early monetization."
        }
    }

    return responses.get(agent_name, {"status": "analysis_complete", "agent": agent_name})


# ─────────────────────────────── AI Service Class ───────────────────────────────

class ClaudeService:
    """Multi-provider AI service: Claude, Gemini, or dynamic mock.
    
    Provider selection (when ai_provider="auto"):
      1. If gemini_api_key is set → use Gemini (free/cheap)
      2. If anthropic_api_key is set → use Claude
      3. Otherwise → use mock mode
    """

    def __init__(self):
        self.mock_mode = settings.mock_mode
        self.provider = self._resolve_provider()
        self.degraded_to_mock = False  # set True if a live request ever falls back to mock
        self._last_call_ts = 0.0       # for the optional inter-call throttle
        self._call_lock = asyncio.Lock()
        # Gemini multi-key rotation: primary key + any comma-separated extras, deduped.
        extra = [k.strip() for k in (settings.gemini_api_keys or "").split(",") if k.strip()]
        seen, self._gemini_keys = set(), []
        for k in ([settings.gemini_api_key] + extra):
            if k and k not in seen:
                seen.add(k)
                self._gemini_keys.append(k)
        self._gemini_rr = 0            # round-robin cursor
        self._gemini_client_cache = {}  # key -> genai.Client
        self.client = None
        self.gemini_model = settings.gemini_model
        self.groq_model = settings.groq_model
        self._clients = {}  # provider -> SDK client (lazy cache for the fallback chain)

        if self.mock_mode:
            logger.info("AI Service initialized (MOCK mode — saving API credits)")
            return

        # Initialize the primary provider's client; alternates are lazy-initialized
        self.client = self._get_client(self.provider)
        if self.client is None:
            logger.warning("No AI provider client available — falling back to DEMO (mock) mode")
            self.mock_mode = True
            self.provider = "mock"
        else:
            logger.info(f"AI Service initialized (primary provider={self.provider})")

    def mode_info(self) -> dict:
        """Effective runtime AI mode, for surfacing in the API/UI.

        Reflects what will ACTUALLY happen on the next call — including the
        silent fallback to mock when no provider client could be created — so
        the frontend can show an honest "DEMO DATA" badge.
        """
        return {
            "mode": "mock" if self.mock_mode else "live",
            "provider": self.provider,
        }

    async def verify_provider(self) -> dict:
        """Confirm the configured provider key actually works, once per process.

        A key can be *present but invalid* (revoked/expired) — in which case
        every request silently falls back to mock. Without this check the UI
        would dishonestly show "live". We do one cheap ping; if it fails we
        honestly degrade to mock so the badge tells the truth. Cached.
        """
        if getattr(self, "_verified", False) or self.mock_mode:
            self._verified = True
            return self.mode_info()

        # JSON-shaped ping: the Groq/Gemini paths enforce JSON output, so a plain-text
        # reply would spuriously fail. Small token budget keeps the check cheap.
        _ping = ("health check", 'Return this exact JSON object: {"status": "ok"}', 50)
        last_err = None
        for provider in self._provider_chain():
            client = self._get_client(provider)
            if client is None:
                continue
            try:
                if provider == "groq":
                    await self._groq_generate(client, *_ping)
                elif provider == "ollama":
                    await self._ollama_generate(*_ping)
                elif provider == "gemini":
                    await self._gemini_generate(client, *_ping)
                else:
                    await self._claude_generate(client, *_ping)
                self.provider = provider
                self._verified = True
                logger.info(f"AI provider verified: {provider}")
                return self.mode_info()
            except Exception as e:
                last_err = e
                logger.warning(f"Provider '{provider}' failed verification: {e}")

        logger.error(f"All AI providers failed verification ({last_err}) — running in DEMO (mock) mode")
        self.mock_mode = True
        self.provider = "mock"
        self._verified = True
        return self.mode_info()

    def _resolve_provider(self) -> str:
        """Determine the primary AI provider."""
        if self.mock_mode:
            return "mock"

        pref = settings.ai_provider.lower()
        if pref == "groq" and settings.groq_api_key:
            return "groq"
        if pref == "claude" and settings.anthropic_api_key:
            return "claude"
        if pref == "gemini" and settings.gemini_api_key:
            return "gemini"
        if pref == "ollama":
            return "ollama"
        if pref == "auto":
            # Prefer Groq (fast + generous free tier), then Gemini, then Claude, then a local model
            if settings.groq_api_key:
                return "groq"
            if settings.gemini_api_key:
                return "gemini"
            if settings.anthropic_api_key:
                return "claude"
            if _ollama_reachable():
                return "ollama"
        return "mock"

    def _gemini_client_for(self, key: str):
        """Lazily create + cache a genai client for a specific key."""
        cli = self._gemini_client_cache.get(key)
        if cli is None:
            try:
                from google import genai
                cli = genai.Client(api_key=key)
                self._gemini_client_cache[key] = cli
            except Exception as e:
                logger.warning(f"Gemini client init failed for a key: {e}")
                return None
        return cli

    async def _throttle(self):
        """Enforce a minimum gap between live calls (free-tier RPM protection)."""
        interval = settings.ai_min_call_interval
        if interval <= 0:
            return
        async with self._call_lock:
            now = time.monotonic()
            wait = self._last_call_ts + interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call_ts = time.monotonic()

    @staticmethod
    def _provider_key(provider: str) -> str:
        return {
            "groq": settings.groq_api_key,
            "gemini": settings.gemini_api_key,
            "claude": settings.anthropic_api_key,
            # a local model needs no key — it is "available" when the server answers
            "ollama": settings.ollama_base_url if _ollama_reachable() else "",
        }.get(provider, "")

    def _provider_chain(self) -> list:
        """Ordered providers to try: primary first, then any other with a key."""
        chain = []
        if self.provider in ("groq", "gemini", "claude", "ollama"):
            chain.append(self.provider)
        for p in ("groq", "gemini", "claude", "ollama"):
            if p not in chain and self._provider_key(p):
                chain.append(p)
        return chain

    def _get_client(self, provider: str):
        """Lazily create and cache the SDK client for a provider (or None)."""
        if provider in self._clients:
            return self._clients[provider]

        client = None
        try:
            if provider == "groq" and settings.groq_api_key:
                from groq import Groq
                client = Groq(api_key=settings.groq_api_key)
            elif provider == "gemini" and settings.gemini_api_key:
                from google import genai
                client = genai.Client(api_key=settings.gemini_api_key)
            elif provider == "claude" and settings.anthropic_api_key:
                from anthropic import Anthropic
                client = Anthropic(api_key=settings.anthropic_api_key)
            elif provider == "ollama" and _ollama_reachable():
                client = settings.ollama_base_url  # plain HTTP API, no SDK object needed
        except ImportError as e:
            logger.warning(f"{provider} SDK not installed: {e}")
        except Exception as e:
            logger.warning(f"{provider} client init failed: {e}")

        self._clients[provider] = client
        return client

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        agent_name: str,
        max_tokens: int = 4096,
    ) -> dict:
        """Generate a response using the configured AI provider.

        Returns:
            dict with keys: content (str), tokens_used (int), cost (float)
        """
        if self.mock_mode:
            return await self._mock_generate(agent_name, user_message)

        await self._throttle()

        # Try each available provider in order, then fall back to mock
        last_err = None
        for provider in self._provider_chain():
            client = self._get_client(provider)
            if client is None:
                continue
            try:
                if provider == "groq":
                    result = await self._groq_generate(client, system_prompt, user_message, max_tokens)
                elif provider == "ollama":
                    result = await self._ollama_generate(system_prompt, user_message, max_tokens)
                elif provider == "gemini":
                    result = await self._gemini_generate(client, system_prompt, user_message, max_tokens)
                else:
                    result = await self._claude_generate(client, system_prompt, user_message, max_tokens)
                result["provider"] = provider
                return result
            except Exception as e:
                last_err = e
                logger.warning(f"Provider '{provider}' failed: {e} — trying next")

        logger.error(f"All providers failed ({last_err}) — falling back to mock for this request")
        # Mark that at least one live request silently degraded to mock this process —
        # lets callers (e.g. the eval) detect token-budget/rate-limit contamination.
        self.degraded_to_mock = True
        return await self._mock_generate(agent_name, user_message)

    async def generate_structured(
        self,
        system_prompt: str,
        user_message: str,
        output_model,
        agent_name: str = "unknown",
        max_tokens: int = 4096,
    ) -> dict:
        """Generate with guaranteed structured output via Claude's tool_use.

        Defines the output Pydantic model as a Claude tool, forces Claude to
        respond via tool_use, then extracts and validates the structured output.
        Falls back to regular generate() + parse for non-Claude providers.

        Returns:
            dict with keys: content (dict — validated), tokens_used (int), cost (float)
        """
        if self.mock_mode:
            return await self._mock_generate(agent_name, user_message)

        await self._throttle()

        # Use the provider's native function/tool calling where supported,
        # validating against the Pydantic model. Anything else (or any failure)
        # falls back to JSON-mode generate() + downstream parsing.
        try:
            if self.provider == "claude":
                client = self._get_client("claude")
                if client is not None:
                    return await self._claude_generate_structured(
                        client, system_prompt, user_message, output_model, agent_name, max_tokens
                    )
            elif self.provider == "groq":
                client = self._get_client("groq")
                if client is not None:
                    return await self._groq_generate_structured(
                        client, system_prompt, user_message, output_model, agent_name, max_tokens
                    )
            elif self.provider == "ollama" and _ollama_reachable():
                # Ollama constrains decoding to the JSON schema itself (structured outputs).
                # The strict variant forbids blank fields, which small models otherwise
                # emit for every optional (defaulted) key.
                result = await self._ollama_generate(
                    system_prompt, user_message, max_tokens, schema=strict_schema(output_model.model_json_schema())
                )
                output_model(**json.loads(result["content"]))  # validate; failure → fallback below
                return result
        except Exception as e:
            logger.warning(f"Structured generation failed for {agent_name}: {e}, falling back to regular")

        return await self.generate(system_prompt, user_message, agent_name, max_tokens)

    async def _claude_generate_structured(self, client, system_prompt, user_message, output_model, agent_name, max_tokens):
        """Claude structured output via tool_use, validated with Pydantic."""
        import json as _json
        tool_schema = output_model.model_json_schema()
        tool_schema.pop("title", None)

        tool_def = {
            "name": "submit_analysis",
            "description": f"Submit the {agent_name} structured analysis output",
            "input_schema": tool_schema,
        }

        response = await asyncio.to_thread(
            client.messages.create,
            model=settings.claude_model,
            max_tokens=max_tokens,
            system=system_prompt,
            tools=[tool_def],
            tool_choice={"type": "tool", "name": "submit_analysis"},
            messages=[{"role": "user", "content": user_message}],
        )

        tool_output = None
        thought_text = ""
        for block in response.content:
            if block.type == "text":
                thought_text += block.text + "\n"
            elif block.type == "tool_use":
                tool_output = block.input
                break

        if tool_output is None:
            raise ValueError("No tool_use block found in Claude response")

        validated = output_model(**tool_output)
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        total_tokens = input_tokens + output_tokens
        cost = (input_tokens * 3.0 / 1_000_000) + (output_tokens * 15.0 / 1_000_000)

        return {
            "content": _json.dumps(validated.model_dump()),
            "provider": "claude",
            "thought": thought_text.strip(),
            "tokens_used": total_tokens,
            "cost": cost,
        }

    async def _groq_generate_structured(self, client, system_prompt, user_message, output_model, agent_name, max_tokens):
        """Groq structured output via function calling, validated with Pydantic."""
        import json as _json
        schema = output_model.model_json_schema()
        schema.pop("title", None)

        tool_def = {
            "type": "function",
            "function": {
                "name": "submit_analysis",
                "description": f"Submit the {agent_name} structured analysis output",
                "parameters": schema,
            },
        }

        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=self.groq_model,
            max_tokens=min(max_tokens, GROQ_MAX_OUTPUT_TOKENS),
            temperature=0.4,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            tools=[tool_def],
            tool_choice={"type": "function", "function": {"name": "submit_analysis"}},
        )

        message = response.choices[0].message
        if not getattr(message, "tool_calls", None):
            raise ValueError("Groq returned no tool call")

        raw_args = message.tool_calls[0].function.arguments
        data = _json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        validated = output_model(**data)

        usage = response.usage
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        total_tokens = input_tokens + output_tokens
        cost = (input_tokens * 0.59 / 1_000_000) + (output_tokens * 0.79 / 1_000_000)

        return {
            "content": _json.dumps(validated.model_dump()),
            "provider": "groq",
            "thought": "",
            "tokens_used": total_tokens,
            "cost": cost,
        }

    async def generate_critique(
        self,
        original_output: str,
        critique_prompt: str,
        agent_name: str = "unknown",
        max_tokens: int = 2048,
    ) -> dict:
        """Generate a self-critique of a previous agent output.

        Used in multi-step reasoning: step 2 (critique) and step 3 (refinement).
        """
        if self.mock_mode:
            await asyncio.sleep(random.uniform(0.3, 0.8))
            return {
                "content": json.dumps({
                    "weaknesses": [
                        "Market size assumptions may be optimistic — needs primary data validation",
                        "Competitor moat analysis is surface-level — deeper differentiation needed",
                        "Timeline assumes ideal hiring velocity which rarely materializes"
                    ],
                    "improvements": [
                        "Add sensitivity analysis for TAM/SAM figures",
                        "Include detailed competitive positioning matrix",
                        "Build contingency buffer of 30% into all timelines"
                    ],
                    "confidence_before": 65,
                    "confidence_after": 82
                }),
                "tokens_used": random.randint(400, 1200),
                "cost": 0.0,
            }

        system = f"You are the self-critique module for {agent_name}. Be brutally honest."
        user_msg = f"{critique_prompt}\n\nPREVIOUS OUTPUT:\n{original_output}"

        return await self.generate(system, user_msg, agent_name, max_tokens)

    async def _mock_generate(self, agent_name: str, user_message: str) -> dict:
        """Return dynamic, input-aware mock response."""
        await asyncio.sleep(random.uniform(0.5, 1.5))
        mock_data = _generate_dynamic_mock(agent_name, user_message)
        return {
            "provider": "mock",
            "content": json.dumps(mock_data),
            "thought": f"Analyzing the brief to formulate {agent_name} strategy. Identifying key market parameters and aligning with the CEO's vision. Extracting insights...",
            "tokens_used": random.randint(800, 2500),
            "cost": 0.0,
        }

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        reraise=True
    )
    async def _groq_generate(
        self,
        client,
        system_prompt: str,
        user_message: str,
        max_tokens: int,
    ) -> dict:
        """Make a real Groq (Llama) API call with JSON output enforced.

        The agent prompts already instruct the model to return JSON, so we use
        Groq's native JSON mode for reliable, parseable structured output.
        """
        # Groq's JSON mode requires the word "json" to appear in the messages.
        system_with_json = (
            f"{system_prompt}\n\nIMPORTANT: Respond ONLY with a single valid JSON object."
        )

        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=self.groq_model,
            max_tokens=min(max_tokens, GROQ_MAX_OUTPUT_TOKENS),
            temperature=0.4,  # Lower temp for reliable structured JSON output
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_with_json},
                {"role": "user", "content": user_message},
            ],
        )

        content = response.choices[0].message.content
        if not content or not content.strip():
            raise ValueError("Groq returned empty response")

        usage = response.usage
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        total_tokens = input_tokens + output_tokens

        # Llama 3.3 70B on Groq pricing: ~$0.59/1M input, ~$0.79/1M output
        cost = (input_tokens * 0.59 / 1_000_000) + (output_tokens * 0.79 / 1_000_000)

        logger.info(f"Groq API call: {total_tokens} tokens, ${cost:.6f}")

        return {
            "content": content,
            "thought": "",
            "tokens_used": total_tokens,
            "cost": cost,
        }

    async def _gemini_generate(
        self,
        client,
        system_prompt: str,
        user_message: str,
        max_tokens: int,
    ) -> dict:
        """Gemini call with round-robin across all configured keys.

        Tries keys starting at the round-robin cursor; on a per-key rate limit
        (429 / RESOURCE_EXHAUSTED) it advances to the next key instead of failing,
        so multiple free-tier keys multiply throughput. The passed `client` is
        ignored in favour of the rotating key pool.
        """
        keys = self._gemini_keys or ([settings.gemini_api_key] if settings.gemini_api_key else [])
        if not keys:
            raise ValueError("No Gemini API key configured")

        last_err = None
        n = len(keys)
        # Gemini returns transient 503 "high demand" spikes; back off and retry the
        # pool before handing the request to the next provider in the chain.
        for backoff in (0, 2, 5):
            if backoff:
                logger.warning(f"Gemini overloaded — retrying in {backoff}s")
                await asyncio.sleep(backoff)
            for i in range(n):
                idx = (self._gemini_rr + i) % n
                cli = self._gemini_client_for(keys[idx])
                if cli is None:
                    continue
                try:
                    result = await self._gemini_call_once(cli, system_prompt, user_message, max_tokens)
                    self._gemini_rr = (idx + 1) % n  # next call starts at the following key
                    return result
                except Exception as e:
                    last_err = e
                    msg = str(e)
                    if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
                        logger.warning(f"Gemini key #{idx + 1} rate-limited — rotating to next key")
                        continue
                    if "503" in msg or "UNAVAILABLE" in msg:
                        break  # whole service is overloaded — back off, then retry
                    raise
            else:
                break  # every key was rate-limited — no point retrying the pool
        raise last_err or RuntimeError("Gemini: all keys failed")

    async def _gemini_call_once(
        self,
        client,
        system_prompt: str,
        user_message: str,
        max_tokens: int,
    ) -> dict:
        """One Gemini API call on a specific client (no retry — rotation handles 429)."""
        from google.genai import types

        combined_prompt = f"{system_prompt}\n\n---\n\n{user_message}"

        # Run sync Gemini call in a thread to keep async
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.models.generate_content(
                model=self.gemini_model,
                contents=combined_prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=max_tokens,
                    temperature=0.4,  # Lower temp for reliable structured JSON output
                    response_mime_type="application/json",
                    # 2.5 Flash "thinks" by default and those hidden tokens count against
                    # max_output_tokens, truncating the JSON mid-object. The agents already
                    # reason explicitly (critique/debate), so spend the budget on the answer.
                    thinking_config=(
                        types.ThinkingConfig(thinking_budget=0)
                        if "flash" in (self.gemini_model or "") else None
                    ),
                ),
            )
        )

        content = response.text
        if not content or not content.strip():
            raise ValueError("Gemini returned empty response")

        # Extract thinking/reasoning if present
        thought = ""
        try:
            if hasattr(response, 'candidates') and response.candidates:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'thought') and part.thought:
                        thought = part.text if hasattr(part, 'text') else ""
        except Exception:
            pass

        # Gemini token counting
        input_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0) or 0
        output_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0) or 0
        total_tokens = input_tokens + output_tokens

        # Gemini 2.5 Flash pricing: $0.15/1M input, $0.60/1M output (very cheap)
        cost = (input_tokens * 0.15 / 1_000_000) + (output_tokens * 0.60 / 1_000_000)

        logger.info(f"Gemini API call: {total_tokens} tokens, ${cost:.6f}")

        return {
            "content": content,
            "thought": thought,
            "tokens_used": total_tokens,
            "cost": cost,
        }

    async def _ollama_generate(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int,
        schema: Optional[dict] = None,
        model: Optional[str] = None,
        num_ctx: Optional[int] = None,
        temperature: float = 0.4,
    ) -> dict:
        """Local model via Ollama's chat API — free, private, no rate limits.

        With `schema`, Ollama constrains decoding to that JSON schema (structured
        outputs); otherwise it enforces plain JSON mode.
        """
        import httpx

        payload = {
            "model": model or settings.ollama_model,
            "messages": [
                {"role": "system", "content": f"{system_prompt}\n\nRespond ONLY with a single valid JSON object."},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
            "format": schema or "json",
            "keep_alive": "30m",
            "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": num_ctx or settings.ollama_num_ctx,
                        "repeat_penalty": 1.1},  # stops small models looping until the token cap
        }
        # A local server can hiccup while it swaps models in and out of VRAM (chat
        # model ↔ RAG embedder); retry briefly rather than degrading the run to mock.
        last_err = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=settings.ollama_timeout) as client:
                    r = await client.post(f"{settings.ollama_base_url}/api/chat", json=payload)
                    r.raise_for_status()
                    data = r.json()
                break
            except Exception as e:
                last_err = e
                logger.warning(f"Ollama call failed (attempt {attempt + 1}/3): {e!r}")
                await asyncio.sleep(2 * (attempt + 1))
        else:
            raise last_err

        content = (data.get("message") or {}).get("content", "")
        if not content.strip():
            raise ValueError("Ollama returned empty response")
        tokens = (data.get("prompt_eval_count") or 0) + (data.get("eval_count") or 0)
        logger.info(f"Ollama ({model or settings.ollama_model}) call: {tokens} tokens, local (free)")
        return {"content": content, "thought": "", "tokens_used": tokens, "cost": 0.0, "provider": "ollama"}

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        reraise=True
    )
    async def _claude_generate(
        self,
        client,
        system_prompt: str,
        user_message: str,
        max_tokens: int,
    ) -> dict:
        """Make a real Anthropic Claude API call (non-blocking)."""
        # Run sync Anthropic SDK call in a thread to avoid blocking the event loop
        response = await asyncio.to_thread(
            client.messages.create,
            model=settings.claude_model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        content = response.content[0].text
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        total_tokens = input_tokens + output_tokens

        # Claude 3.5 Sonnet pricing: $3/1M input, $15/1M output
        cost = (input_tokens * 3.0 / 1_000_000) + (output_tokens * 15.0 / 1_000_000)

        logger.info(f"Claude API call: {total_tokens} tokens, ${cost:.4f}")

        return {
            "content": content,
            "tokens_used": total_tokens,
            "cost": cost,
        }

    async def write_agent_log(
        self,
        workflow_id,
        agent_name: str,
        *,
        tokens: int = 0,
        cost: float = 0.0,
        latency_ms: int = 0,
        status: str = "success",
        provider: Optional[str] = None,
        input_preview: str = "",
        output_preview: str = "",
    ) -> None:
        """Persist one LLM call to the AgentLog table for observability.

        No-ops when workflow_id is absent (standalone agent runs / tests).
        Best-effort: any DB error is swallowed so logging never breaks a run.
        The blocking insert runs in a worker thread.
        """
        if not workflow_id:
            return

        provider = provider or ("mock" if self.mock_mode else self.provider)
        model_name = {
            "groq": self.groq_model,
            "gemini": self.gemini_model,
            "claude": settings.claude_model,
            "ollama": settings.ollama_model,
        }.get(provider) or provider

        def _insert():
            from app.database import get_session_factory
            from app.models.db_models import AgentLog
            db = get_session_factory()()
            try:
                db.add(AgentLog(
                    workflow_id=workflow_id,
                    agent_name=agent_name,
                    total_tokens=tokens,
                    cost_usd=cost,
                    latency_ms=latency_ms,
                    model_provider=provider,
                    model_name=model_name,
                    status=status,
                    input_preview=(input_preview or "")[:500],
                    output_preview=(output_preview or "")[:500],
                ))
                db.commit()
            except Exception as e:
                db.rollback()
                logger.debug(f"AgentLog write skipped: {e}")
            finally:
                db.close()

        try:
            await asyncio.to_thread(_insert)
        except Exception as e:
            logger.debug(f"AgentLog offload skipped: {e}")


# ─────────────────────────────── Singleton ───────────────────────────────

_claude_service: Optional[ClaudeService] = None


def get_claude_service() -> ClaudeService:
    global _claude_service
    if _claude_service is None:
        _claude_service = ClaudeService()
    return _claude_service
