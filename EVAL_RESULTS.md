# AgentForge — Multi-Agent Evaluation Results

_Generated 2026-07-03 · provider: `gemini` · 4 business ideas · blind LLM judge · A/B order alternated to cancel position bias._

## Headline

- **Pipeline overall score:** 6.55/10  vs  **baseline:** 6.65/10  (**-1.5%**)
- **Head-to-head:** pipeline won **2/4**, baseline won 2/4, ties 0
- **Cost of the win:** pipeline used ~22.1× the tokens of the baseline (159,770 vs 7,233).

## Scores by dimension (mean across ideas, 1-10)

| Dimension | Pipeline | Baseline | Δ |
|---|---|---|---|
| specificity | 5.75 | 6.50 | -0.75 |
| internal consistency | 7.50 | 7.75 | -0.25 |
| actionability | 7.00 | 6.75 | +0.25 |
| risk depth | 6.25 | 5.25 | +1.00 |
| realism | 6.25 | 7.00 | -0.75 |

## Per-idea results

| Idea | Winner | Pipeline | Baseline |
|---|---|---|---|
| fittech | pipeline | 8.4 | 5.2 |
| agri-iot | baseline | 7.2 | 8.0 |
| legal-saas | pipeline | 5.4 | 5.4 |
| resale | baseline | 5.2 | 8.0 |

## Methodology

- **Baseline:** a single strong-prompt LLM call (senior-analyst persona, generous token budget, asked to cover the same sections) — a deliberately strong baseline, not a strawman.
- **Pipeline:** the real 7 agents (CEO → Research/Marketing/Developer/Finance → Analytics → Operations) plus the Board Meeting debate, run via the production agent classes.
- **Judge:** a separate blind LLM call scoring both anonymized blueprints on the rubric above. Which blueprint is labelled 'A' vs 'B' is alternated per idea so position bias cancels out.
- **Reproduce:** `cd backend && python -m eval.run`. Raw per-idea artifacts are saved under `backend/eval/results/`.

## Caveats (read honestly)

- The judge is an LLM and shares the failure modes of LLMs; treat these as directional, not exact.
- Baseline and judge use the same provider tier as the pipeline, so absolute quality tracks the model.
- The pipeline costs meaningfully more tokens/latency — the question this answers is whether that buys enough quality to justify it, per the numbers above.
