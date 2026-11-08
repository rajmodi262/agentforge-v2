"""Data-analysis report: charts + findings computed from the export tables.

Every sentence with a number in analytics/ANALYSIS.md is generated from the data,
so re-running after a new hunt updates the findings, not just the charts.

    python -m app.phantom.analysis      → analytics/ANALYSIS.md + analytics/charts/*.png
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean, median
from typing import Any, Dict, List

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt  # noqa: E402

from app.phantom.export import ANALYTICS, tables  # noqa: E402
from app.phantom.score import LAYERS  # noqa: E402

CHARTS = ANALYTICS / "charts"
VIOLET, CYAN, GREEN, AMBER, RED, INK = "#7C3AED", "#06B6D4", "#10B981", "#F59E0B", "#EF4444", "#1E1B4B"


def _style(ax, title: str, xlabel: str = "", ylabel: str = ""):
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold", color=INK)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="y", alpha=0.25)


def _save(fig, name: str) -> str:
    CHARTS.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(CHARTS / f"{name}.png", dpi=130)
    plt.close(fig)
    return f"charts/{name}.png"


def gw(mw: float) -> str:
    return f"{mw / 1000:.1f} GW" if mw >= 1000 else f"{mw:,.0f} MW"


def analyse(data: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    P = data["projects"]
    capped = [p for p in P if p["capacity_mw"]]
    f: Dict[str, Any] = {"n": len(P), "n_capped": len(capped)}
    f["announced"] = sum(p["capacity_mw"] for p in capped)
    f["real"] = sum(p["reality_mw"] for p in capped)

    # stage
    f["by_stage"] = {l: {"n": 0, "mw": 0.0, "real": 0.0} for l in LAYERS}
    for p in P:
        s = f["by_stage"][p["stage_name"]]
        s["n"] += 1
        s["mw"] += p["capacity_mw"] or 0
        s["real"] += p["reality_mw"] or 0

    # state
    st = defaultdict(lambda: {"mw": 0.0, "real": 0.0, "n": 0})
    for p in capped:
        k = f"{p['state'] or 'Place not stated'}, {p['country']}"
        st[k]["mw"] += p["capacity_mw"]
        st[k]["real"] += p["reality_mw"]
        st[k]["n"] += 1
    f["by_state"] = sorted(st.items(), key=lambda kv: -(kv[1]["mw"] - kv[1]["real"]))[:10]

    # developer concentration
    dev = defaultdict(lambda: {"mw": 0.0, "real": 0.0, "n": 0})
    for p in capped:
        if p["developer"]:
            d = dev[p["developer"]]
            d["mw"] += p["capacity_mw"]
            d["real"] += p["reality_mw"]
            d["n"] += 1
    f["devs"] = sorted(dev.items(), key=lambda kv: -kv[1]["mw"])
    top5 = sum(v["mw"] for _, v in f["devs"][:5])
    f["top5_share"] = top5 / f["announced"] if f["announced"] else 0

    # coverage vs score
    buckets = {"1": [], "2": [], "3–4": [], "5+": []}
    for p in P:
        n = p["n_sources"] or 0
        buckets["1" if n <= 1 else "2" if n == 2 else "3–4" if n <= 4 else "5+"].append(p["reality_score"])
    f["coverage"] = {k: (len(v), mean(v) if v else 0) for k, v in buckets.items()}

    # bands
    f["bands"] = Counter(p["score_band"] for p in P)
    f["median_score"] = median(p["reality_score"] for p in P) if P else 0

    # evidence quality
    ev = data["evidence"]
    f["evidence"] = len(ev)
    f["headline_share"] = sum(1 for e in ev if e["text_kind"] == "summary") / len(ev) if ev else 0
    q = Counter()
    for e in ev:
        if e["event_date"]:
            y, m = int(e["event_date"][:4]), int(e["event_date"][5:7])
            q[f"{y}-Q{(m + 2) // 3}"] += 1
    f["quarters"] = sorted(q.items())[-8:]

    # sales
    f["open_power"] = [p for p in P if not p["power_partner"] and p["stage"] <= 3 and p["reality_score"] >= 0.45 and (p["capacity_mw"] or 0) >= 50]
    f["open_power_mw"] = sum(p["reality_mw"] or 0 for p in f["open_power"])
    f["anomalies"] = Counter(a["kind"] for a in data["anomalies"])
    return f


def charts(f: Dict[str, Any]) -> Dict[str, str]:
    out = {}
    # 1. ladder
    fig, ax = plt.subplots(figsize=(8, 4))
    xs = range(len(LAYERS))
    ax.bar([x - 0.2 for x in xs], [f["by_stage"][l]["mw"] / 1000 for l in LAYERS], 0.4, label="Announced", color=VIOLET)
    ax.bar([x + 0.2 for x in xs], [f["by_stage"][l]["real"] / 1000 for l in LAYERS], 0.4, label="Reality-weighted", color=GREEN)
    ax.set_xticks(list(xs), [f"{l}\n({f['by_stage'][l]['n']})" for l in LAYERS])
    ax.legend(frameon=False)
    _style(ax, "Capacity by highest verified evidence (projects in brackets)", ylabel="GW")
    out["ladder"] = _save(fig, "01_capacity_by_stage")

    # 2. phantom gap by state
    fig, ax = plt.subplots(figsize=(8, 4.6))
    names = [k for k, _ in f["by_state"]][::-1]
    real = [v["real"] / 1000 for _, v in f["by_state"]][::-1]
    gap = [(v["mw"] - v["real"]) / 1000 for _, v in f["by_state"]][::-1]
    ax.barh(names, real, color=GREEN, label="Likely (reality-weighted)")
    ax.barh(names, gap, left=real, color=RED, alpha=0.75, label="Phantom gap")
    ax.legend(frameon=False, loc="lower right")
    _style(ax, "Where the phantom capacity sits — top 10 regions by gap", xlabel="GW")
    ax.grid(axis="x", alpha=0.25)
    out["states"] = _save(fig, "02_phantom_gap_by_region")

    # 3. developers
    fig, ax = plt.subplots(figsize=(8, 4.6))
    top = f["devs"][:12]
    for name, v in top:
        share = v["real"] / v["mw"] if v["mw"] else 0
        ax.scatter(v["mw"] / 1000, share * 100, s=60 + 40 * v["n"], color=GREEN if share >= 0.5 else AMBER if share >= 0.35 else RED, alpha=0.7)
        ax.annotate(name, (v["mw"] / 1000, share * 100), fontsize=8, xytext=(5, 4), textcoords="offset points")
    _style(ax, "Developers: announced vs real (bubble size = projects)", "Announced GW", "Reality share %")
    out["developers"] = _save(fig, "03_developers")

    # 4. coverage
    fig, ax = plt.subplots(figsize=(7, 3.8))
    ks = list(f["coverage"])
    ax.bar(ks, [f["coverage"][k][1] * 100 for k in ks], color=CYAN)
    for i, k in enumerate(ks):
        ax.text(i, f["coverage"][k][1] * 100 + 1, f"n={f['coverage'][k][0]}", ha="center", fontsize=9)
    _style(ax, "Average reality score by number of independent sources", "Sources", "Avg reality score %")
    out["coverage"] = _save(fig, "04_score_vs_sources")

    # 5. momentum
    if f["quarters"]:
        fig, ax = plt.subplots(figsize=(8, 3.6))
        ax.plot([q for q, _ in f["quarters"]], [n for _, n in f["quarters"]], marker="o", color=VIOLET, linewidth=2)
        _style(ax, "Verified evidence items per quarter", ylabel="Evidence items")
        out["momentum"] = _save(fig, "05_momentum")
    return out


def report(f: Dict[str, Any], imgs: Dict[str, str]) -> str:
    bs = f["by_stage"]
    pre = sum(bs[l]["mw"] for l in LAYERS[:3])
    live_build = bs["LIVE"]["mw"] + bs["BUILDING"]["mw"]
    s1n, s1 = f["coverage"]["1"]
    s5n, s5 = f["coverage"]["5+"]
    worst = f["by_state"][0] if f["by_state"] else None
    share = lambda kv: kv[1]["real"] / kv[1]["mw"]  # noqa: E731
    big = [kv for kv in f["devs"][:12] if kv[1]["mw"]]
    risky_devs = sorted((kv for kv in big if share(kv) < 0.35), key=share)
    strong_devs = sorted((kv for kv in big if share(kv) >= 0.5), key=share, reverse=True)
    qs = f["quarters"]
    L = [
        "# Phantom Hunter — data analysis",
        "",
        f"Generated by `python -m app.phantom.analysis` on {datetime.now(timezone.utc):%Y-%m-%d}. "
        "Every number is computed from the current database, so re-running after a new hunt updates the findings.",
        "",
        "## Key findings",
        "",
        f"1. **Only {f['real'] / f['announced']:.0%} of announced capacity looks real.** {f['n_capped']} of {f['n']} projects state a capacity: "
        f"{gw(f['announced'])} announced, {gw(f['real'])} reality-weighted. The other {gw(f['announced'] - f['real'])} is phantom risk.",
        f"2. **Most capacity is still paper.** {gw(pre)} ({pre / f['announced']:.0%}) sits at ANNOUNCED / SITE / APPROVED; "
        f"only {gw(live_build)} ({live_build / f['announced']:.0%}) has verified BUILDING or LIVE evidence.",
    ]
    if worst:
        L.append(f"3. **The biggest gap is {worst[0]}**: {gw(worst[1]['mw'])} announced across {worst[1]['n']} projects with a stated capacity, "
                 f"{gw(worst[1]['real'])} likely — a {gw(worst[1]['mw'] - worst[1]['real'])} gap.")
    def names(devs):
        return ", ".join("{} ({:.0%})".format(n, v["real"] / v["mw"]) for n, v in devs[:3])
    L.append(f"4. **The pipeline is concentrated.** The top 5 developers account for {f['top5_share']:.0%} of announced MW. "
             + (f"Highest reality share among the big names: {names(strong_devs)}. " if strong_devs else "")
             + (f"Lowest: {names(risky_devs)}." if risky_devs else ""))
    L.append(f"5. **Corroboration matters.** {s1n} projects ({s1n / f['n']:.0%}) rest on a single source and average {s1:.0%}; "
             f"projects with 5+ sources average {s5:.0%}. The single biggest lever for confidence is a second independent source.")
    L.append(f"6. **Publishers block bots.** {f['headline_share']:.0%} of verified evidence comes from headlines/summaries, not full articles — "
             "which is why the scorer applies a headline-only penalty and why permit / utility filings are the next data source.")
    if len(qs) >= 2:
        L.append(f"7. **Momentum is rising.** Verified evidence went from {qs[-2][1]} items in {qs[-2][0]} to {qs[-1][1]} in {qs[-1][0]} "
                 "(the latest quarter may still be partial).")
    L.append(f"8. **Sales opportunity.** {len(f['open_power'])} projects are likely enough (≥45%), at least 50 MW, pre-construction and have **no power partner named** — "
             f"{gw(f['open_power_mw'])} of reality-weighted demand an IPP could still bid for.")
    L += ["", "## Charts", ""]
    caps = {"ladder": "Capacity by evidence stage", "states": "Phantom gap by region", "developers": "Developers: announced vs real",
            "coverage": "Reality score vs number of sources", "momentum": "Evidence momentum"}
    for k, path in imgs.items():
        L += [f"### {caps[k]}", "", f"![{caps[k]}]({path})", ""]
    L += ["## Score distribution", "", "| Band | Projects |", "|---|---|"]
    L += [f"| {b} | {n} |" for b, n in sorted(f["bands"].items())]
    L += ["", f"Median reality score: {f['median_score']:.0%}.", "",
          "## Caveats", "",
          "- Reality scores are **stated priors + named adjustments**, not yet calibrated against outcomes (see `PHANTOM_HUNTER.md` §4.4).",
          "- Coverage reflects what public news reports; projects that never make the news are invisible (recall is not measured).",
          "- A few projects may appear twice when the resolver was not confident enough to merge them (by design).",
          ""]
    return "\n".join(L)


def main():
    data = tables()
    f = analyse(data)
    imgs = charts(f)
    out = ANALYTICS / "ANALYSIS.md"
    out.write_text(report(f, imgs), encoding="utf-8")
    print(f"wrote {out.name} + {len(imgs)} charts")


if __name__ == "__main__":
    main()
