# 🎬 AgentForge — Demo Runbook

Everything you need to run a smooth demo. Verified working end-to-end (mock + live).

---

## ⏰ 10 minutes before (DO THIS — the dry run)

A 60-second dry run catches any surprise. **Do it before the audience is watching.**

1. Double-click **`Start_AgentForge.bat`**. Two terminal windows open; the browser opens to **http://localhost:5180** automatically (~20-30s).
2. In the browser, scroll to the **"Launch"** input, type a business idea (e.g. *"An AI study planner for college students in India"*), click launch.
3. Watch the agents stream. Confirm it reaches **"Blueprint Generation Complete"** and a report link appears.
4. If it streamed and finished → **you're good, leave it running.**
5. If it looked stuck or showed errors → flip to bulletproof mock mode (see **Fallback** below) and re-run. Mock always works.

> Tip: the **first** live run of the day is the riskiest (cold quota). Doing the dry run *is* your insurance.

---

## 🚀 Launching

- **One double-click:** `Start_AgentForge.bat` — it **kills any old servers, reinstalls dependencies, then starts** backend (`:8000`) + frontend (`:5180`) and opens the browser. Allow **~2–3 minutes** (the dependency check runs every launch by design — it guarantees a clean start).
- ✅ Verified end-to-end on 2026-07-03: launcher → both servers live → real Gemini workflow → PDF generated.
- Backend API docs (if asked): http://localhost:8000/docs
- Health check: http://localhost:8000/health

---

## 🎤 The 3-minute flow

1. **Open on the landing page.** Let the hero/animation land for a beat — it looks polished.
2. **Type a business idea** into the Launch box. Pick something relatable to the audience.
3. **Click launch → narrate the live stream** as it happens:
   - "Seven specialist agents spin up — CEO frames the idea, then Research, Marketing, Developer and Finance run **in parallel**."
   - "Then Analytics and Operations build on their output."
   - "They enter a **Board Meeting** — the agents actually challenge each other's assumptions."
   - "Finally a **Chief Synthesizer** weaves it all into one coherent blueprint."
4. **Open the generated PDF report** — scroll through the sections (market, GTM, tech, financials, ops, risks).
5. **Close with the technical flex** (see talking points).

---

## 💬 Talking points (what makes this strong)

- **Real orchestration, not a wrapper:** "It's a LangGraph state machine with genuine parallel fan-out/fan-in, live WebSocket streaming, and a multi-step reasoning loop per agent."
- **The honesty flex (your differentiator):** "I didn't just *claim* multiple agents are better — I built an **evaluation harness** that pits the pipeline against a single strong prompt, scored by a blind LLM judge. It refuses to report fake numbers if it can't reach a real model." → open **`EVAL_RESULTS.md`** if asked.
  - The measured result: roughly a **tie overall** on a free-tier model — but the **Board-Meeting debate measurably improves risk analysis (+1.0/10 risk depth)**. Say it straight: *"I report the tie honestly; the debate stage is where multi-agent earns its cost, and my next step is preserving specialist detail through synthesis."* Owning an honest result impresses far more than a fake win.
- **Production touches:** JWT auth with bcrypt + rate limiting, multi-provider fallback (Gemini/Groq) with key rotation, truncation-tolerant parsing, **109 passing tests + CI**.
- If the "DEMO DATA" badge appears: *"That's the system being honest — it flags when it's using simulated data instead of a live model, so output is never mistaken for real analysis."* (This is a feature, not a bug — own it.)

---

## 🛟 Fallback plan (if anything misbehaves live)

**Option A — let it self-heal:** the system auto-falls back to mock per-request if the LLM is rate-limited; the demo keeps streaming.

**Option B — force bulletproof mock mode** (12-second guaranteed run, no internet/quota):
1. Open `backend/.env`
2. Change `MOCK_MODE=false` → **`MOCK_MODE=true`**
3. Restart the backend window (close it, re-run `Start_AgentForge.bat`)

To go back to live: set `MOCK_MODE=false` again.

---

## 🧰 Props to have open in tabs (backup if live is slow)

- A pre-generated PDF: `backend/generated_reports/` (newest file)
- `EVAL_RESULTS.md` — the measured pipeline-vs-baseline scorecard
- `http://localhost:8000/docs` — the live API surface (shows real engineering)

---

## ⚙️ Current config (set for "live with mock fallback")

- `MOCK_MODE=false` · `AI_PROVIDER=gemini` · model **`gemini-2.5-flash`** (the smart one)
- 3 Gemini keys rotating + Groq fallback + `AI_MIN_CALL_INTERVAL=1.5` (rate-limit safety)
- Live run takes ~1-2 min; mock takes ~12s.
- **Quota budget on 2.5-flash: ~4 full runs per day** (20 req/day/key × 3 keys, ~15 calls per run). Dry run + 2 live demos fits. If quota dies mid-run it falls back to Groq, then labeled mock — the demo never crashes. For unlimited runs, change `GEMINI_MODEL=gemini-2.5-flash-lite` in `backend/.env` (lower quality, huge quota).
- The PDF now leads with the **Master Blueprint (synthesized)** and the **Board Verdict with consensus score** — scroll those two sections in the demo finale.

**You've got this. 🚀**
