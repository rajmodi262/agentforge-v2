"""AgentForge evaluation harness.

Measures whether the 7-agent pipeline (+ Board Meeting debate) actually produces
a better startup blueprint than a single strong-prompt baseline, scored by a
blind LLM judge across a rubric. Run with:  python -m eval.run
"""
