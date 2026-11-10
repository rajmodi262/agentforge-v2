# 👻 Phantom Hunter — Reality-Scored Data-Centre Pipeline Intelligence

> *Every data centre announced is a promise. Phantom Hunter tells you which promises will keep their power on — and who to call before your competitor does.*

**What it is:** an agentic AI system that reads public news about data-centre projects in **India and Malaysia (Johor)**, extracts structured evidence with a local LLM, **verifies every claim against its source text**, resolves duplicate mentions into projects, and scores how likely each project is to really be built. It then tells suppliers (power, electrical, cooling) **which projects to call this month** and why.

**Built by:** Raj Modi, Levinesh GR, Aaditya Kumar Sinha, Krishna Renuse. Runs fully on a laptop (Ollama + qwen2.5:7b), no paid API.

---

## 0. Results at a glance

| | |
|---|---|
| Articles collected (Bing News, Google News, GDELT, Firecrawl search) | 1,761 → 793 relevant → 666 read by the local LLM, **section by section, whole article** |
| Full-text coverage (Firecrawl reads pages plain HTTP can't) | 247 → **681** full-text articles; verified evidence resting on headlines only **44% → 4.5%** |
| Claims checked by the deterministic verifier | 4,135 — **87.1% survived** |
| Projects resolved (India + Malaysia) | **403** (was 208 before full-article reading); 38.5% have 2+ independent sources (was 28.8%) |
| Announced vs reality-weighted capacity | **82.6 GW → 35.1 GW (43%)** — ~47.5 GW is phantom risk |
| Verifier planted-error test | **4,068 / 4,136 caught (98.4%)**, 0 false rejections in 1,856 untouched fields |
| Human audit of verified evidence | **62.5% → 77.5%** fully correct (round 2 = fresh sample, not the one we tuned on). After full-article reading, BUILDING/LIVE evidence fell to ~58% (quotes about *other* projects in long articles); the subject check brought a fresh sample back to **31/40 (77.5%)** |
| Recall vs published lists | **89% strict** of 36 pipeline sites (was 64%) from Wikipedia, Black Ridge, Mordor and DCK (extracted with Firecrawl); misses listed in `PHANTOM_EVAL.md` §5 |
| Calibration backtest | 67 projects re-scored as of 30 Jun 2024 with only the evidence known then, outcome read from later news: **Brier 0.097** vs 0.22 for always guessing the base rate (§6 of `PHANTOM_EVAL.md`) |
| Coverage agent ablation | its own follow-up queries added **+29 projects** (174 → 203) |
| Analytics pack | Excel workbook (live SUMIFS + charts), Google Sheets formulas, Power BI dataset + 17 DAX measures, 11 SQL queries, computed findings — see `analytics/` |
| Tests | 56 Phantom tests (no LLM, no network); full backend suite 175 passed |
| Try it | a fresh clone loads the real dataset on first start (`backend/seed/`) — no API key needed to explore |

## 1. The problem — in the market's own words

| Source | What it says |
|---|---|
| Bernstein | Only ~35% of the US data-centre pipeline looks credible |
| Capgemini (2026, 600+ power executives) | ~1 in 5 interconnection requests never become real load; 67% report "phantom" load |
| Sightline Climate | 30–50% of 2026 US capacity at risk of delay or cancellation |
| SemiAnalysis | "Half cancelled" is wrong as a whole — withdrawals sit in the **announcement layer** |
| Cushman & Wakefield | APAC: 26.5 GW pipeline in H1 2026, only ~1.4 GW delivered that half |

**The argument everyone is having:** how much of the announced pipeline is real? SemiAnalysis points to the answer — *it depends on which evidence layer a project has reached.* Phantom Hunter makes that the core of the product: every project is placed on an **evidence ladder**, and every rung must be backed by a verified quote.

**Who needs it:** companies that *sell into* data centres — power generation and IPPs, transformer/switchgear/UPS makers, cooling vendors. They told the market (DCD / DCWA 2026) they want **earlier visibility into credible projects**, because specifications are set **12–18 months before ground-break**, and **insights that translate into actions**.

---

## 2. Three-minute demo script

1. **Dashboard** (`/phantom`) — "Announced capacity X GW; reality-weighted Y GW. The difference is the phantom capacity."
2. **Reality Globe** — ghost bar = announced MW, solid bar = reality-weighted MW. Rotate to Johor. *"Look how much of Johor's pipeline is still only an announcement."*
3. **Who to call this month** → Power & IPPs tab. *"These projects are likely real, have no energy partner named yet, and are inside the 12–24 month spec window."*
4. Click a project → **dossier**: evidence ladder lit rung by rung, every quote linked to its article, the score broken down term by term, the **weakest assumption** in plain English.
5. **Bull vs Bear** — two agents argue from the evidence only; the Judge's *watch for* is the next fact that would change the verdict.
6. **How every claim was checked** — open it and show green/red verdicts per field. *"The LLM proposes, the verifier disposes."*
7. **Ask the Tracker** — "Which Johor projects are most likely real?" → cited answer, each [S#] links to the project.

---

## 3. Architecture

```
            ┌──────────── LangGraph hunt (agentic loop) ────────────┐
            │                                                        │
 Planner ─► Scouts ─► Extractor ─► Verifier ─► Resolver ─► Scorer ─► Coverage agent
  (seed     (Bing,    (local LLM,   (no LLM:    (same project,  (evidence     │ writes next round's
  queries)  Google,   structured    every claim  different      ladder →      │ queries for weak spots
            GDELT)    output) +     vs source)   names → one)   reality %,    ▼
                      Evidence                                  anomalies,   loop until nothing
                      Miner (rules)                             who-to-call) worth chasing / budget
            └────────────────────────────────────────────────────────┘
                     Bull vs Bear debate · Ask-the-Tracker chat · Reality Globe UI
```

| Agent | File | Uses an LLM? | Job |
|---|---|---|---|
| Planner + Scouts | `phantom/sources.py` | no | Query 3 news feeds in parallel, de-duplicate, fetch article text politely |
| Evidence Extractor | `phantom/extract.py` | **yes** (qwen2.5:7b) | Article → projects, developers, capacity, stage events, each with a quote |
| Evidence Miner | `phantom/extract.py` | no | Precise stage language in sentences about the project ("broke ground", "commissioned") |
| Verifier | `phantom/verify.py` | **no — on purpose** | Every claim must appear in the article; numbers must parse; stage quotes must fit the stage |
| Resolver | `phantom/resolve.py` | no | Many mentions → one project (facility codes, aliases, fuzzy names, place, capacity) |
| Scorer | `phantom/score.py` | no | Transparent log-odds reality score, weakest assumption, anomalies, who-to-call |
| Coverage agent | `phantom/pipeline.py` | no | Inspects results, writes the next round's search queries for weak spots |
| Bull / Bear / Judge | `phantom/debate.py` | **yes** | Argue from verified evidence only; uncited points are discarded |
| Ask the Tracker | `phantom/chat.py` | **yes** | RAG over the project DB; every answer cites [S#] sources |

**Stack:** FastAPI · SQLAlchemy (SQLite / Postgres) · LangGraph · Pydantic · Ollama (qwen2.5:7b, local) · rapidfuzz · trafilatura · React 19 · react-three-fiber (3D globe).

---

## 4. Design decisions — and the alternatives we rejected

**4.1 "LLM proposes, verifier disposes."** The LLM is good at reading messy news and finding entities; it is bad at being trusted. So every LLM output passes a *deterministic* verifier: the quote must exist in the article (exact, or ≥90 fuzzy), the capacity text must exist and parse to the stated MW (±2%), names and years must appear, and a stage quote must contain that stage's language. *Rejected:* asking a second LLM to fact-check — a model grading a model inherits the same failure modes.

**4.2 Ensemble extraction: LLM for entities, rules for evidence.** In testing, the 7B model often left quotes empty and under-read stages ("AdaniConneX **opens** its campus" came back as ANNOUNCED). The Evidence Miner scans only the sentences about the project (plus the next two, stopping if another developer appears) for precise stage language and rejects future/hedged tense. Because it is deterministic, it is **re-run on every rebuild**, so improving a rule upgrades all historical data without another LLM call.

**4.3 "Power" means secured, not mentioned.** An early version counted any sentence with the word *power* — "AI computing power" became secured power. Now POWER requires PPA / grid connection / substation / kV / utility language, and **requirement or intention language never counts** ("Lodha **must build** substations" is a risk, not evidence). A missed POWER costs a project a few points; a fake one inflates it — so the rule errs conservative.

**4.4 Transparent log-odds score, not a black box.** `logit(p) = logit(prior[layer]) + Σ adjustments`. Priors per layer are **stated assumptions anchored to the public numbers above** (announced 25%, site 40%, approved 50%, power 75%, building 88%, live 98%); adjustments are named (single source −0.3, ≥3 sources +0.3, headline-only −0.2, financing +0.4, delayed −0.6, opposition −0.5, gone quiet −0.5, target passed −0.5; cancelled ⇒ 3%). Every term is shown in the UI. *Rejected:* a trained classifier — there are no outcome labels yet, and an interpretable model is what a commercial team can defend to a customer. `score.calibrate()` is ready for when outcomes exist.

**4.5 Weakest assumption = counterfactual, but only what an analyst would chase next.** For each candidate missing fact (next ladder rung, secured power, a second source, full-text access) we recompute the score as if it existed; the biggest uplift wins. Restricting candidates matters — "not live yet" is always the biggest uplift and is useless.

**4.6 Entity resolution is conservative.** Facility codes (JHB2, NOI2, MAA10) are the strongest identity signal; two different codes are never merged. Otherwise names must be similar *after removing capacity and adjectives* ("52 MW AI-ready data centre" ≈ "Vyoma.AI"), places must not conflict, capacities must agree within ±35%. Anonymous mentions with no developer, code, or brand are not merged at all. *Why:* a wrong merge silently corrupts a project; a missed merge just shows two cards.

**4.7 Honest scraping.** robots.txt honoured, an honest User-Agent (no browser impersonation), 1 request/second/domain, GDELT ≤1 request/5 s, everything cached. When publishers block us we keep the headline + summary and mark that evidence **weaker** (−0.2 logit). Public sources only, no personal data.

**4.8 Local model.** Free, private, no rate limits — and the verifier makes a small model trustworthy. Cost per full hunt: $0. Trade-off: ~20–60 s per long article on a 4 GB laptop GPU, so batch extraction runs in the background.

---

## 5. Evaluation

See `PHANTOM_EVAL.md` (regenerated by `python -m app.phantom.evaluate`).

* **Verifier planted-error test** — real verified mentions corrupted one field at a time (inflated capacity, shifted year, swapped developer, invented quote, mislabelled stage) and re-verified.
* **False-rejection check** — untouched verified fields must stay verified.
* **Human audit, two rounds** — `PHANTOM_AUDIT_SAMPLE_round1.csv` / `_round2.csv`: 40 random verified evidence items each (is the stage right? is the quote about this project?). Round 1: 25/40; the fixes it drove were tested on a *fresh* round-2 sample: 31/40. Labels are a first pass and should be confirmed by the team. This measures the one error the verifier cannot catch: a real quote about a *different* project in the same article.
* **Recall vs published lists** — 42 sites from four independent sources (`PHANTOM_RECALL_REFERENCE.csv`): 89% strict on pipeline sites (64% before the Firecrawl gap scout).
* **Calibration backtest** — `backtest.py`: every project first seen by 30 Jun 2024 is re-scored with only the evidence published by then, then compared with verified BUILDING/LIVE evidence since (regular hunt + Firecrawl outcome scout). 67 projects, Brier 0.097 (base-rate guess 0.22); on the 53 not yet under construction at the cutoff, Brier 0.12. Small sample, and "no progress found" is a lower bound.
* **Not yet measured:** calibration at scale (a few hundred outcomes) and recall on the long tail of small projects.

---

## 6. Questions an FSX interviewer will ask — with answers

**Data**
1. *Where does the data come from?* Bing News RSS, Google News RSS and the GDELT DOC API, queried per city and per developer for India and Malaysia, then full article text where the publisher allows it.
2. *Is it legal / ethical?* Public news only; robots.txt honoured; honest User-Agent; polite rate limits; we store text only to re-verify claims; no personal data.
3. *How fresh is it?* As fresh as the last hunt. A hunt is incremental (known URLs/titles/bodies are skipped), so it can run daily — that's the path from quarterly to continuous refresh.
4. *What happens when a site blocks you?* We keep headline + summary, mark the article `summary`, and the score penalises headline-only evidence.

**Correctness**
5. *How do you know the LLM didn't make it up?* The deterministic verifier (§4.1). The planted-error test measures it: see `PHANTOM_EVAL.md`.
6. *What can the verifier not catch?* A real quote that fits the stage but describes a different project in the same article. That's why the miner stops its sentence window at another developer's name, and why the human audit sample exists.
7. *What's your extraction precision?* Precision of *verified* claims is what the audit sample measures; the verifier's catch rate on planted errors is in the eval.
8. *Same project, different names?* §4.6 — codes first, then cleaned-name similarity + place + capacity agreement; conservative by design.
9. *MW IT vs facility vs campus?* Every capacity keeps its basis (IT / facility / campus / unknown). The canonical value prefers the most specific basis; conflicts are kept and flagged by Anomaly Watch, never averaged.
10. *Two sources disagree?* Most recent verified value with the most specific basis wins for display; the disagreement itself becomes an anomaly ("capacity cut 300 → 150 MW") — that's often the most valuable signal.

**Scoring**
11. *Why these layers?* They follow how a project physically becomes real — intent, land, permission, power, construction, operation — and they match the evidence layers SemiAnalysis uses in the "phantom pipeline" debate.
12. *Where do the probabilities come from? Are they calibrated?* They are stated priors anchored to public numbers (§4.4). A first backtest exists: projects seen before 30 Jun 2024, scored with only the evidence known then, against what later news shows — Brier 0.097 on 67 projects vs 0.22 for a base-rate guess, and the 80–100% bucket progressed 100% of the time. It is a small sample and absence of news is not proof of failure, so the priors stay stated assumptions until a few hundred outcomes can re-fit them.
13. *Why put POWER above APPROVED?* For AI data centres, power is the binding constraint (IEA: ~20% of planned projects at risk of grid delays). A permit without power is common; power without a permit is rare.
14. *What's the weakest assumption?* §4.5 — counterfactual uplift over the facts an analyst would chase next.
15. *How does "who to call" work?* priority = reality × timing × size × openness. Openness: no energy partner named (power), pre-construction (electrical — specs set 12–18 months before ground-break), cooling not disclosed / AI density (cooling). Every rank lists its reasons.

**Agents & LLM**
16. *Why agents and not a pipeline?* Most of it *is* a deterministic pipeline, on purpose. The agentic parts are where judgement helps: the Coverage agent decides what to search next from what it found (single-source projects, missing capacity, unseen developers); the extractor self-corrects (retries with a hint when an article clearly names a developer and a capacity but nothing was extracted); Bull vs Bear stress-tests a verdict.
17. *Why a local model?* §4.8. The verifier is what makes a small model safe to use.
18. *Why 7B and not 3B?* Measured on the same articles: 3B missed developers and stages; 7B found them. 7B was given guardrails (output cap, repeat penalty, timeout) after it looped once.
19. *How do you stop the debate from hallucinating?* Agents only see numbered verified evidence; points must cite evidence ids; uncited points are dropped (the Bear may argue from *missing* evidence, labelled as such). The debate never changes the score — it explains it.
20. *Hallucination in chat?* Retrieval over the project DB; the model must cite [S#]; citations that don't exist are stripped.

**Scale & product**
21. *How would this scale to 8,000+ projects?* Extraction is embarrassingly parallel (one article at a time); swap Ollama for a hosted small model or batch API; Postgres instead of SQLite; the resolver blocks by (developer, country) so comparisons stay small; the verifier and scorer are pure CPU and fast.
22. *How would it fit a platform like Energy for AI?* As a module: a reality score + evidence ladder per project, a weekly "what changed" anomaly feed, and a who-to-call ranking per buyer segment.
23. *What would you add next?* Permit and utility filings as sources (stronger than news), back-testing on cancelled projects for calibration, ISO/utility interconnection queues, alerting.

**Lessons from real data (good stories to tell)**
- *Joint ventures:* Indian news often credits **Digital Realty** for what **Digital Connexion** (its JV) is building. Treating them as different developers split one Visakhapatnam campus into three. A small (parent, country) → JV map fixed it; after the fix that campus has 6 corroborating sources.
- *Adjectives are not identity:* "YTL Corp 500MW campus" and "YTL 500MW Sustainable Campus" are the same Johor campus. Capacity tokens ("1GW") and adjectives ("sustainable", "flagship", "AI-ready") are stripped before names are compared.
- *The model writes placeholders:* when it doesn't know a name it sometimes writes the literal text "null" or "Not specified". These are treated as no name; the project is named from its place and capacity instead.
- *Not every MW is a data centre:* a 29.99 MW solar farm and a 900 MW fuel-cell supply deal were extracted as "projects". Names that describe deals, solar/wind/hydro plants or storage are rejected as non-facilities.
- *Headlines hide the partner:* the dossier for DayOne Selangor said "power partner: none named" while its own verified POWER evidence read "signs 1.5GW renewable supply deal with **TNB**". Headline-only articles leave the LLM's field empty, so the partner is now read from the verified POWER quote with a small utility gazetteer — and who-to-call stops pitching power to a project that already has it.
- *Out of scope leaks in:* "DayOne Nurmijärvi" (Finland) was attributed to Kuala Lumpur because the article mentioned the company's HQ. A name that itself contains a foreign place is now out of scope.

**Analytics & business tooling**
24c. *Our team works in Sheets and Power BI, not in your app — how do we use this?* `analytics/`: a formatted Excel workbook whose KPIs and analysis are live formulas (they work unchanged in Google Sheets), star-schema CSVs plus DAX measures for Power BI, and 11 SQL queries answering the commercial questions (phantom gap by state, developer league table with RANK, power-sales target list). All are generated from the same database by code, so they can never disagree with the dashboard. The dashboard has Excel and CSV download buttons.
24d. *Show me one SQL query you're proud of.* `market_share_by_country`: a CTE sums reality-weighted MW per developer, then `SUM() OVER (PARTITION BY country)` gives each developer's share of its own country and `ROW_NUMBER()` ranks them — one pass, no self-join.

**Honesty**
24. *Biggest limitation?* News coverage is uneven, so 62% of projects still rest on one source; and the calibration backtest is small (67 projects). Full-article reading also creates a new risk — a long article names several projects — which the subject check handles with rules, not understanding.
24a. *How many real projects did you miss?* I checked against 42 sites from four published lists that the system never saw (Wikipedia, Black Ridge Research, Mordor Intelligence, Data Center Knowledge), pulled with Firecrawl and cleaned by hand. On the 36 pipeline sites, the first run found 64% at the right developer and state. Misses clustered in smaller operators (Pi, Infinaxis, Open DC, AIMS) and second sites of known developers (CapitaLand Airoli, Iron Mountain Chennai), so the Firecrawl gap scout searched for exactly those; recall is now 89% strict (32 of 36). The remaining misses are listed in `PHANTOM_EVAL.md` §5. Caveat: the gap scout was aimed at the reference list, so 89% overstates recall on sites nobody listed. Facility codes are treated as identity, so our JHB1 never counts as their JHB2.
24e. *What did Firecrawl actually change?* Three things, measured against a backup of the database taken before it: (1) **reading** — 265 headline-only articles were re-read in full (8k → 269k words); full-text articles 247 → 681 and evidence resting on headlines alone 44% → 4.5%; (2) **finding** — three targeted scouts: recall gaps (sites the recall check said we missed), official sources (PIB, Invest India, MIDA…; few project-level hits — honest result) and outcomes (what happened to every project seen before the backtest cutoff); recall 64% → 89%; (3) **the backtest itself** — outcome news is what makes §6 possible. About 530 credits on the free plan; robots.txt is still respected on the final URL, and Firecrawl is only the fallback after a free direct fetch.
24f. *More text should mean more errors — did it?* Yes, at first. Reading whole articles, the LLM credited stage sentences to the wrong project (an MY07 construction line on MY03, a Patna opening on a Bodh Gaya project, tracker-table rows, "related stories" headlines). A sample of BUILDING/LIVE evidence fell to ~58% correct. A subject check now drops a quote that names another facility code, another state or Indian metro, another developer, a portfolio-wide fact, a future plan, or page boilerplate; a fresh 40-item sample came back at 31/40 (77.5%), level with the pre-Firecrawl audit. Duplicates rose too (one Reliance Vizag campus under 8 names); the resolver now merges same developer + same place + compatible capacity whatever the wording, and drops "projects" with no place, size or code — 560 raw clusters → 403.
24b. *I see two DayOne cards and two Digital Connexion cards — duplicates?* Sometimes, yes. The resolver merges only when it is confident (same facility code, or similar name + same place + capacity within ±35%). "DayOne 500 MW" (no place) vs "DayOne Selangor 1.5 GW" disagree on capacity, so they stay apart. That is deliberate: a wrong merge silently corrupts a project, a missed merge just shows two cards a human can join. Next step: a "possible duplicate" queue for an analyst.
25. *What surprised you?* How often "power" in an article doesn't mean power is secured — fixing that changed which projects looked real.

---

## 7. How to run

```bash
# 1. local model (free)
ollama pull qwen2.5:7b
# backend/.env:  AI_PROVIDER=ollama  OLLAMA_MODEL=qwen2.5:7b  PHANTOM_EXTRACT_MODEL=qwen2.5:7b
# 2. backend + frontend
Start_AgentForge.bat          # or: uvicorn app.main:app --port 8000  /  npm run dev
# 3. open http://localhost:5180/phantom  → "Hunt Malaysia" / "Hunt India"
# batch extraction of stored articles / rebuild / evaluation:
python -m app.phantom.run_extract
python -m app.phantom.evaluate
```

Tests: `pytest tests/test_phantom.py` — verifier, miner, resolver, scorer, gazetteer, scouts (no LLM, no network).
