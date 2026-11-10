"""Targeted scouts (query building) and the calibration backtest (no network, no LLM)."""

from datetime import datetime, timezone

from app.phantom.backtest import run, section
from app.phantom.targeted import _q, official_queries


def test_queries_are_short_and_deduplicated():
    assert _q("CapitaLand India", "CapitaLand DC Navi Mumbai Tower 2 (Airoli)", "Navi Mumbai") == "CapitaLand India DC Navi Mumbai Tower 2 data centre"
    assert all("site:" in q for qs in official_queries().values() for q in qs)


def _m(i, name, dev, published, events):
    return {"id": i, "article_id": f"a{i}", "text_kind": "full", "published": published,
            "data": {"project_name": name, "developer": dev, "country": "Malaysia", "city": "Kulai", "capacity_mw": 100, "events": events}}


def test_backtest_scores_with_past_evidence_only_and_reads_the_outcome_after():
    old, new = datetime(2023, 3, 1, tzinfo=timezone.utc), datetime(2025, 9, 1, tzinfo=timezone.utc)
    ms = [
        _m(1, "YTL Kulai campus", "YTL", old, [{"layer": "ANNOUNCED", "quote": "YTL announced", "published": old}]),
        _m(2, "YTL Kulai campus", "YTL", new, [{"layer": "BUILDING", "quote": "Construction began on the 100 MW Kulai campus", "published": new}]),
        _m(3, "AirTrunk JHB9", "AirTrunk", old, [{"layer": "ANNOUNCED", "quote": "AirTrunk plans JHB9", "published": old}]),
    ]
    res = run(ms)
    rows = {r["name"]: r for r in res["rows"]}
    ytl = next(r for n, r in rows.items() if "YTL" in n)
    assert ytl["stage_then"] == "ANNOUNCED" and ytl["stage_now"] == "BUILDING" and ytl["progressed"]
    assert ytl["reality_score"] < 0.5                       # scored as of the cutoff, before construction was known
    assert not next(r for n, r in rows.items() if "JHB9" in n)["progressed"]
    assert res["all"]["n"] == 2 and "Brier" in "\n".join(section(res))
