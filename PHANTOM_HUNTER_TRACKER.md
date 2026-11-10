# 👻 Phantom Hunter — Live Build Tracker

> *Every data centre announced is a promise. Phantom Hunter tells you which promises will keep their power on — and who to call before your competitor does.*

Built on the AgentForge engine (LangGraph agents, structured output, verifier, RAG, 3D UI, local LLM).
Scope: **India + Malaysia (Johor)** data-centre pipeline, public sources only.

**Legend:** ✅ done · 🔨 in progress · ⏳ next · ⚠️ issue found

---

## Build log (newest first)

| Time | Status | Work | Evidence / result |
|---|---|---|---|
| 10 Nov | ✅ | **Firecrawl upgrade**: whole-article reading (section by section), re-fetch of 257 headline-only articles, three targeted scouts (gaps / official / outcomes), calibration backtest | full text 247 → 681 · headline-only evidence 44% → 4.5% · recall 64% → **89%** · backtest Brier **0.097** on 67 projects (base rate 0.22) |
| 10 Nov | ⚠️→✅ | Overnight rebuild crashed (LLM wrote capacity_basis "hyperscale"); then 560 projects with duplicates and ~58% correct BUILDING/LIVE evidence. Fixes: tolerant sort, merge on developer + place + capacity, drop placeless/sizeless clusters, subject check on evidence | **403 projects**; fresh audit sample 31/40 (77.5%); 175 tests pass |
| 10 Nov | ✅ | **Recall check** against 42 sites from 4 published lists (Firecrawl search + JSON extraction, 24 credits), matched by developer group + state, facility codes as identity | pipeline recall **63.9% strict / 75.0%** incl. location-unknown; misses listed in PHANTOM_EVAL.md §5 |
| 10 Nov | ✅ | **Seed snapshot**: fresh clones load the real dataset on first start (no article bodies, no users) | rebuild from snapshot reproduces 208 projects exactly |
| 08 Nov 19:10 | ✅ | **Final state.** Full backend suite **145 passed, 0 errors** (26 Phantom tests). Dashboard + dossier re-checked in the browser with full data, no console errors | see numbers below |
| 08 Nov 19:00 | ⚠️→✅ | Dossier said "power partner: none named" while its own POWER evidence read "supply deal with **TNB**" (headline-only articles leave the LLM field empty). Added a utility gazetteer that names the partner from the *verified* POWER quote | 5 projects now name a partner (TNB ×4, CleanMax); who-to-call stops pitching power to them |
| 08 Nov 18:55 | ⚠️→✅ | Dashboard said 90.8% verified, the eval said 87.5% (one averaged per mention, one pooled all claims). Both now call the same `claim_tally()` | one number everywhere: **87.5% of 1,404 claims** |
| 08 Nov 18:45 | ⚠️→✅ | 30 test errors: the `/start` endpoint tests launched a real background workflow that outlived the test and raced the next test's table drop on the shared in-memory SQLite connection | endpoint tests now stub the workflow (orchestration is covered by `test_orchestrator.py`) |
| 08 Nov 18:20 | ✅ | **Final evaluation** | verifier 1,449/1,454 planted errors caught (**99.7%**), 688/688 untouched fields kept; audit **25/40 → 31/40** on a fresh sample; coverage agent **+29 projects** (174 → 203) |
| 08 Nov 17:30 | ✅ | Extraction finished: 1,485 articles → 609 relevant → 495 read → 435 mentions → **208 projects** | **37.1 GW announced → 15.1 GW reality-weighted (41%)** |
| 08 Nov 01:45 | ✅ | Probed free data sources | Bing News RSS ✅ real links · Google News RSS ✅ · GDELT ✅ (max 1 req / 5 s) · some publishers block bots → fall back to headline + summary |
| 08 Nov 01:47 | ✅ | Installed trafilatura (article text), rapidfuzz (fuzzy matching), feedparser (RSS) | — |
| 08 Nov 04:00 | ✅ | README now leads with Phantom Hunter; full write-up + 25 interview Q&A in `PHANTOM_HUNTER.md` | — |
| 08 Nov 03:50 | ⚠️→✅ | **"Power" was too easy to earn**: any sentence with the word *power* counted ("AI computing power"). Now POWER needs PPA / grid connection / substation / kV / utility language, and hedged language ("must build substations", "plans to") never proves a stage. Rules re-applied retroactively at every rebuild | 10 POWER items → 1 genuine ("220kV GIS substation located on campus") |
| 08 Nov 03:40 | ✅ | **Evaluation harness**: funnel, verifier planted-error test, false-rejection check, 40-item human audit CSV | first run: **108/110 planted errors caught (98.2%)**, 0/46 false rejections |
| 08 Nov 03:30 | ✅ | **Security lock-down**: prompts (admin to change), n8n (admin + SSRF guard), MCP tool calls (admin), observability (own runs only), knowledge (login + 10 MB cap), share (owner only; fixed broken query + path) | anonymous → 401 everywhere except public data; normal user → 403 on admin actions |
| 08 Nov 03:20 | ✅ | Browser check: dashboard, Reality Globe (grid + country labels), dossier, live **Bull vs Bear** (verdict LIKELY BUILT; Bear: "No power agreement") | screenshots in session |
| 08 Nov 03:15 | ✅ | Resolver fixes from real data: "STT GDC" vs "STTGDC" merged via facility code NOI2; deal names ("900 MW fuel-cell agreement") rejected; out-of-scope (Jakarta) dropped; country inferred from places/currency; stable project ids | — |
| 08 Nov 03:05 | 🔨 | Full extraction batch restarted (7B, guarded) | 510 relevant articles; progress in `phantom_extract.log` |
| 08 Nov 03:00 | ✅ | **Evidence Miner** (deterministic): stage language only in sentences that mention the project; future tense rejected; new FINANCED signal | JHB2 → FINANCED ("The loan for its JHB2 … was led by 10 global coordinators"); Chennai 1 → LIVE ("AdaniConneX opens its flagship … campus") |
| 08 Nov 02:45 | ⚠️→✅ | Found: 7B often leaves quotes empty and under-reads stages; 3B misses developers | Fixed with quote rescue + miner + nearest-developer gazetteer |
| 08 Nov 02:30 | ⚠️→✅ | 7B looped on one article for minutes | Output cap 1,100 tokens, repeat penalty 1.1, 150 s per-article timeout |
| 08 Nov 02:20 | ✅ | Scorer: transparent log-odds reality score, weakest assumption (counterfactual), Anomaly Watch, who-to-call, calibration function | `app/phantom/score.py` |
| 08 Nov 02:15 | ✅ | Resolver (facility codes, developer aliases, offline gazetteer of 29 places) | `resolve.py`, `geo.py` |
| 08 Nov 02:10 | ✅ | Bull vs Bear debate (citations enforced) + Ask-the-Tracker chat (citations enforced) | `debate.py`, `chat.py` |
| 08 Nov 02:05 | ✅ | LangGraph hunt: plan → scout → extract → resolve → **coverage agent writes next round's queries** | `pipeline.py` |
| 08 Nov 01:58 | ✅ | **Seed hunt: 62 queries → 1,096 articles stored** (403 MY, 693 IN), 510 relevant (174 full text, 336 headline-only) | DB `ph_articles` |
| 08 Nov 01:55 | ✅ | Extractor (LLM, structured) + **Verifier** (deterministic, no LLM) | first real test: JHB2 / KUL1 / Vantage Johor found; market stats correctly rejected |
| 08 Nov 01:50 | ✅ | Design + interview guide | this file |

---

## Task board

| # | Task | Status |
|---|---|---|
| 1 | Live tracker + design | ✅ |
| 2 | Verify data sources + deps | ✅ |
| 3 | **Scouts** — multi-source acquisition with coverage-driven query loop | ✅ |
| 4 | **Evidence Extractor** (LLM, structured) + **Verifier** (deterministic) + **Evidence Miner** | ✅ |
| 5 | **Entity resolution** + project store | ✅ |
| 6 | **Evidence-ladder scorer**, weakest assumption, anomalies, who-to-call | ✅ |
| 7 | **Bull vs Bear** debate + **Ask the Tracker** cited chat | ✅ |
| 8 | API + frontend: **Reality Globe** dashboard, project dossier page | ✅ |
| 9 | Real collection run: India + Malaysia (1,485 articles, 609 relevant, 208 projects) | ✅ |
| 10 | Evaluation: verifier catch rate, extraction audit (2 rounds), agentic-scout ablation | ✅ `PHANTOM_EVAL.md` |
| 11 | Security lock-down, tests (26 Phantom; full suite 145 passed), README, interview guide | ✅ |
| 12 | End-to-end browser verification | ✅ |

---

## Design (what we're building and why)

### The problem (FSX's words)
- FSX sells **Energy for AI**: project-by-project data-centre intelligence, "evidence scored against public filings", refreshed quarterly.
- The market's loudest argument: **how much of the announced pipeline is real?** (Bernstein ~35% credible; Capgemini ~1 in 5 interconnection requests never materialise; Sightline 30–50% of 2026 US capacity at risk; SemiAnalysis: depends on the *evidence layer*.)
- What FSX customers asked for at DCD/DCWA: **earlier visibility into credible projects**, decisions shaped **12–18 months before RFQs**, insights that **translate into actions**.

### The pipeline (each box is an agent)
```
 Scouts ──► Extractor ──► Verifier ──► Resolver ──► Scorer ──► Anomaly Watch ──► Who-to-Call
 (news,      (LLM →       (quote must   (same project,  (evidence     (capacity cuts,    (per buyer
  RSS,        structured   exist in      different       ladder →      date slips,        segment)
  GDELT)      evidence)    source)       names → one)    reality %)    opposition)
                                                            │
                                               Bull vs Bear debate · Ask-the-Tracker chat
```

### The evidence ladder
| Layer | Meaning | Example evidence |
|---|---|---|
| 0 ANNOUNCED | plan / MoU / intent | "plans to invest ₹X in a 300 MW campus" |
| 1 SITE | land acquired / leased | "acquired 20 acres in Navi Mumbai" |
| 2 APPROVED | permits, clearances, state approval | "received environmental clearance" |
| 3 POWER | power secured: PPA, grid agreement, substation | "signed a 200 MW PPA with Tata Power" |
| 4 BUILDING | construction / ground-break / EPC awarded | "began construction" |
| 5 LIVE | operational / energised / commissioned | "commissioned phase 1 (30 MW)" |
| ⛔ negative | delayed, cancelled, opposition, scaled down | "project put on hold" |

---

## Interviewer questions → where the answer lives

| # | What an FSX interviewer will ask | Answer (filled in as we build) |
|---|---|---|
| 1 | Where does the data come from? Legal? Fresh? | Bing News, Google News, GDELT; robots.txt honoured, honest User-Agent, rate-limited, public news only; incremental hunts → daily refresh possible (§6 Q1–4 in PHANTOM_HUNTER.md) |
| 2 | How do you know the LLM extraction is right? Precision? | Deterministic verifier — quote must exist, numbers must parse, stage quote must fit the stage. Planted-error test: 98.2% caught, 0% false rejections (PHANTOM_EVAL.md) |
| 3 | Same project, different names — de-duplication? | Facility codes first (JHB2, NOI2), then cleaned-name similarity + place + capacity agreement; anonymous mentions never merged (§4.6) |
| 4 | MW IT vs facility vs campus — units normalised? | Every capacity keeps its basis (IT / facility / campus); most specific wins; conflicts become anomalies, never averaged (§6 Q9) |
| 5 | Two sources disagree — which wins? | Latest verified, most specific basis wins for display — the disagreement itself is flagged ("capacity cut 300 → 150 MW") (§6 Q10) |
| 6 | Why these evidence layers? Where do probabilities come from? Calibrated? | Layers follow how a project becomes physically real; priors are stated assumptions anchored to Bernstein / Capgemini / Sightline numbers — **not calibrated yet**; `calibrate()` ready for outcome data (§4.4) |
| 7 | What exactly is the "weakest assumption"? | Counterfactual: the missing fact (next rung, secured power, second source, full text) whose presence raises the score most (§4.5) |
| 8 | Why agents and not a plain pipeline? What did agents add? | Mostly a deterministic pipeline on purpose; agentic where judgement helps: coverage agent writes next searches, extractor self-corrects, Bull vs Bear stress-tests (§6 Q16) |
| 9 | Why a local model? Cost, latency, hallucination? | $0, private, no rate limits; verifier makes a small model safe; 7B chosen over 3B after measuring both (§4.8, Q18) |
| 10 | How would it scale to 8,000+ projects and continuous refresh? | Parallel extraction, hosted small model or batch API, Postgres, resolver blocking keeps comparisons small (§6 Q21) |
| 11 | Biggest limitation? | Uneven news coverage + publisher blocking (many projects rest on headlines) and an uncalibrated score (§6 Q24) |
