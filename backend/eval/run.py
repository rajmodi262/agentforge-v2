"""Eval driver:  python -m eval.run [--ideas N] [--out EVAL_RESULTS.md]

For each business idea it generates a single-prompt baseline blueprint and the
full 7-agent pipeline blueprint, then a blind judge scores both on a rubric.
A/B order is alternated per idea to cancel position bias. Results (per-idea +
aggregate) are written to a markdown scorecard and raw artifacts are saved.
"""

import os
import json
import asyncio
import argparse
import datetime as _dt
from statistics import mean

from app.services.claude_service import get_claude_service
from eval.ideas import IDEAS
from eval.blueprint import render_markdown
from eval.baseline import generate_baseline
from eval.pipeline import run_pipeline
from eval.judge import judge_pair, DIMENSIONS

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIM_NAMES = [name for name, _ in DIMENSIONS]


def _avg_scores(scores: dict) -> float:
    vals = [float(scores.get(d, 0)) for d in DIM_NAMES]
    return mean(vals) if vals else 0.0


async def _eval_one(idea_obj: dict, index: int, claude) -> dict:
    """Run baseline + pipeline + judge for a single idea. Returns a record."""
    idea = idea_obj["idea"]
    print(f"\n[{index + 1}] {idea_obj['id']}: {idea[:60]}...")

    print("    -> baseline (1 call)...")
    baseline_bp, baseline_tokens = await generate_baseline(idea, claude)

    print("    -> pipeline (7 agents + board + synthesis)...")
    pipeline_bp, agent_outputs, pipeline_tokens = await run_pipeline(idea)

    baseline_md = render_markdown(baseline_bp)
    pipeline_md = render_markdown(pipeline_bp)

    # Alternate A/B assignment per idea to cancel position bias.
    pipeline_is_a = index % 2 == 0
    doc_a, doc_b = (pipeline_md, baseline_md) if pipeline_is_a else (baseline_md, pipeline_md)

    print("    -> judging (blind)...")
    verdict = await judge_pair(idea, doc_a, doc_b, claude)

    # De-anonymize
    if pipeline_is_a:
        pipeline_scores, baseline_scores = verdict.get("A", {}), verdict.get("B", {})
        winner_label = {"A": "pipeline", "B": "baseline", "tie": "tie"}.get(verdict.get("winner"), "tie")
    else:
        pipeline_scores, baseline_scores = verdict.get("B", {}), verdict.get("A", {})
        winner_label = {"B": "pipeline", "A": "baseline", "tie": "tie"}.get(verdict.get("winner"), "tie")

    # Persist raw artifacts for transparency
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, f"{idea_obj['id']}.json"), "w", encoding="utf-8") as f:
        json.dump({
            "idea": idea_obj, "pipeline_is_a": pipeline_is_a,
            "baseline_blueprint": baseline_bp, "pipeline_blueprint": pipeline_bp,
            "verdict": verdict,
        }, f, indent=2, ensure_ascii=False)

    print(f"    winner: {winner_label}  "
          f"(pipeline {_avg_scores(pipeline_scores):.1f} vs baseline {_avg_scores(baseline_scores):.1f})")

    return {
        "id": idea_obj["id"],
        "idea": idea,
        "winner": winner_label,
        "pipeline_scores": pipeline_scores,
        "baseline_scores": baseline_scores,
        "rationale": verdict.get("rationale", ""),
        "baseline_tokens": baseline_tokens,
        "pipeline_tokens": pipeline_tokens,
    }


def _render_report(records: list, provider: str) -> str:
    n = len(records)
    wins = sum(1 for r in records if r["winner"] == "pipeline")
    losses = sum(1 for r in records if r["winner"] == "baseline")
    ties = sum(1 for r in records if r["winner"] == "tie")

    def dim_mean(records, side, dim):
        vals = [float(r[side].get(dim, 0)) for r in records if r[side]]
        return mean(vals) if vals else 0.0

    p_overall = mean([_avg_scores(r["pipeline_scores"]) for r in records]) if n else 0.0
    b_overall = mean([_avg_scores(r["baseline_scores"]) for r in records]) if n else 0.0
    delta_pct = ((p_overall - b_overall) / b_overall * 100) if b_overall else 0.0

    p_tokens = sum(r["pipeline_tokens"] for r in records)
    b_tokens = sum(r["baseline_tokens"] for r in records)
    token_ratio = (p_tokens / b_tokens) if b_tokens else 0.0

    today = _dt.date.today().isoformat()
    lines = [
        "# AgentForge — Multi-Agent Evaluation Results",
        "",
        f"_Generated {today} · provider: `{provider}` · {n} business ideas · "
        f"blind LLM judge · A/B order alternated to cancel position bias._",
        "",
        "## Headline",
        "",
        f"- **Pipeline overall score:** {p_overall:.2f}/10  vs  **baseline:** {b_overall:.2f}/10  "
        f"(**{delta_pct:+.1f}%**)",
        f"- **Head-to-head:** pipeline won **{wins}/{n}**, baseline won {losses}/{n}, ties {ties}",
        f"- **Cost of the win:** pipeline used ~{token_ratio:.1f}× the tokens of the baseline "
        f"({p_tokens:,} vs {b_tokens:,}).",
        "",
        "## Scores by dimension (mean across ideas, 1-10)",
        "",
        "| Dimension | Pipeline | Baseline | Δ |",
        "|---|---|---|---|",
    ]
    for dim in DIM_NAMES:
        p = dim_mean(records, "pipeline_scores", dim)
        b = dim_mean(records, "baseline_scores", dim)
        lines.append(f"| {dim.replace('_', ' ')} | {p:.2f} | {b:.2f} | {p - b:+.2f} |")

    lines += [
        "",
        "## Per-idea results",
        "",
        "| Idea | Winner | Pipeline | Baseline |",
        "|---|---|---|---|",
    ]
    for r in records:
        lines.append(
            f"| {r['id']} | {r['winner']} | {_avg_scores(r['pipeline_scores']):.1f} | "
            f"{_avg_scores(r['baseline_scores']):.1f} |"
        )

    lines += [
        "",
        "## Methodology",
        "",
        "- **Baseline:** a single strong-prompt LLM call (senior-analyst persona, generous token "
        "budget, asked to cover the same sections) — a deliberately strong baseline, not a strawman.",
        "- **Pipeline:** the real 7 agents (CEO → Research/Marketing/Developer/Finance → Analytics → "
        "Operations) plus the Board Meeting debate and the Chief Synthesizer editor stage, run via "
        "the production agent classes.",
        "- **Judge:** a separate blind LLM call scoring both anonymized blueprints on the rubric above. "
        "Which blueprint is labelled 'A' vs 'B' is alternated per idea so position bias cancels out.",
        "- **Reproduce:** `cd backend && python -m eval.run`. Raw per-idea artifacts are saved under "
        "`backend/eval/results/`.",
        "",
        "## Caveats (read honestly)",
        "",
        "- The judge is an LLM and shares the failure modes of LLMs; treat these as directional, not exact.",
        "- Baseline and judge use the same provider tier as the pipeline, so absolute quality tracks the model.",
        "- The pipeline costs meaningfully more tokens/latency — the question this answers is whether that "
        "buys enough quality to justify it, per the numbers above.",
        "",
    ]
    return "\n".join(lines)


async def main():
    parser = argparse.ArgumentParser(description="AgentForge multi-agent eval")
    parser.add_argument("--ideas", type=int, default=len(IDEAS), help="how many ideas to evaluate")
    parser.add_argument("--out", default=os.path.join(REPO_ROOT, "EVAL_RESULTS.md"),
                        help="output markdown path (default: repo-root EVAL_RESULTS.md)")
    args = parser.parse_args()

    claude = get_claude_service()
    # Ping the provider — a present-but-invalid key would otherwise silently
    # fall back to mock and produce meaningless 0/0 scores.
    await claude.verify_provider()
    if claude.mock_mode:
        print("\n[X] AI is in MOCK mode (no working API key) -- the eval needs a real LLM.")
        print("  Get a free key at https://console.groq.com, put it in backend/.env as")
        print("  GROQ_API_KEY=..., then retry. (Your current key returned 401 Invalid API Key.)\n")
        raise SystemExit(1)

    provider = claude.mode_info()["provider"]
    ideas = IDEAS[: args.ideas]
    print(f"Running eval on {len(ideas)} ideas with provider={provider}...")

    records = []
    for i, idea_obj in enumerate(ideas):
        try:
            records.append(await _eval_one(idea_obj, i, claude))
        except Exception as e:
            print(f"    ! idea '{idea_obj['id']}' failed: {e}")

    # Drop records contaminated by a mid-run fallback to mock (e.g. rate-limit /
    # daily-token-budget exhaustion). A real verdict has non-empty score dicts.
    valid = [r for r in records
             if r["pipeline_scores"] and r["baseline_scores"]
             and (_avg_scores(r["pipeline_scores"]) + _avg_scores(r["baseline_scores"])) > 0]
    dropped = len(records) - len(valid)
    if dropped:
        print(f"\n! Dropped {dropped}/{len(records)} ideas — calls fell back to mock "
              f"(provider rate-limit / daily token budget).")
    if claude.degraded_to_mock and not valid:
        print("\n[X] Every idea hit the provider's token/rate limit and degraded to mock.")
        print("    No real data was produced, so no report was written (refusing to emit fake zeros).")
        print("    Fix: wait for the daily reset and run `python -m eval.run --ideas 2`, or add a")
        print("    GEMINI_API_KEY (more generous free tier) to backend/.env and retry.")
        raise SystemExit(1)
    if len(valid) < 2:
        print(f"\n[X] Only {len(valid)} clean idea(s) — too few for a credible report. Not writing.")
        raise SystemExit(1)

    records = valid
    report = _render_report(records, provider)
    out_path = os.path.abspath(args.out)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n[OK] Wrote {out_path}  ({len(records)}/{len(ideas)} ideas)")


if __name__ == "__main__":
    asyncio.run(main())
