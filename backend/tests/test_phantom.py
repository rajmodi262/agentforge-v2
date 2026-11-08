"""Phantom Hunter — tests for every deterministic component (no LLM, no network)."""

from datetime import datetime, timezone

from app.phantom import score as S
from app.phantom.extract import NON_FACILITY, gazetteer_developer, mine_evidence, project_sentences
from app.phantom.geo import infer_country, resolve_place
from app.phantom.resolve import canonical_developer, facility_code, resolve
from app.phantom.sources import is_relevant, normalise_title
from app.phantom.verify import parse_capacity, verify_mention

ARTICLE = (
    "AirTrunk signs deal for JHB2 in Johor\n"
    "AirTrunk said its JHB2 hyperscale data centre in Kulai, Johor, will have 150MW of IT capacity. "
    "The company has signed a power purchase agreement with Tenaga Nasional for the campus. "
    "Construction began in March 2025 and the first phase is due in 2027."
)


# ── Verifier ──

def test_capacity_parsing():
    assert parse_capacity("150MW") == 150
    assert parse_capacity("1.2 GW") == 1200
    assert parse_capacity("no number") is None


def test_verifier_keeps_supported_claims():
    m = {"project_name": "JHB2", "developer": "AirTrunk", "city": "Kulai", "capacity_mw": 150, "capacity_text": "150MW",
         "target_year": 2027, "events": [{"layer": "POWER", "detail": "PPA", "quote": "The company has signed a power purchase agreement with Tenaga Nasional for the campus."}]}
    clean, v, ratio = verify_mention(m, ARTICLE)
    assert ratio == 1.0
    assert clean["capacity_mw"] == 150 and clean["events"][0]["layer"] == "POWER"


def test_verifier_rejects_hallucinated_number_and_quote():
    m = {"project_name": "JHB2", "developer": "AirTrunk", "capacity_mw": 300, "capacity_text": "300MW", "target_year": 2026,
         "events": [{"layer": "LIVE", "detail": "live", "quote": "JHB2 has been fully operational since January."}]}
    clean, v, ratio = verify_mention(m, ARTICLE)
    assert clean["capacity_mw"] is None and clean["target_year"] is None
    assert clean["events"] == []
    assert ratio < 0.5


def test_verifier_rejects_quote_that_does_not_fit_its_layer():
    m = {"project_name": "JHB2", "events": [{"layer": "POWER", "detail": "x", "quote": "Construction began in March 2025 and the first phase is due in 2027."}]}
    clean, v, _ = verify_mention(m, ARTICLE)
    assert clean["events"] == [] and "doesn't describe POWER" in v["events"][0]["why"]


def test_power_means_secured_not_mentioned():
    from app.phantom.verify import event_fits
    assert event_fits("POWER", "The facility will benefit from a 220kV GIS substation located on campus.")
    assert event_fits("POWER", "YTL signed a power purchase agreement with TNB for 300MW.")
    assert not event_fits("POWER", "Adding 60MW means we benefit from the power, the cooling and the network.")
    assert not event_fits("POWER", "Demand for AI computing power is rising across Johor.")
    assert not event_fits("POWER", "To connect the 5 GW park, Lodha must build high-voltage substations at its own expense.")


def test_hedged_language_never_proves_a_stage():
    from app.phantom.verify import event_fits
    assert not event_fits("BUILDING", "The company plans to begin construction later this year.")
    assert event_fits("BUILDING", "Construction began in March 2025.")
    assert not event_fits("LIVE", "The supercluster is expected to go live by August.")
    assert not event_fits("SITE", "SIPP Power will acquire approximately 58.6 hectares within STeP.")


def test_audit_findings_upgrades_and_rejections():
    """Regression tests for the human-audit findings (PHANTOM_EVAL.md §3)."""
    from app.phantom.extract import upgrade_events
    from app.phantom.verify import event_fits
    up = lambda q: {e["layer"] for e in upgrade_events([{"layer": "ANNOUNCED", "quote": q}])}  # noqa: E731
    assert "POWER" in up("TM Nxera has signed a multi-year electricity supply agreement with Tenaga Nasional (TNB) to secure 280 megawatt.")
    assert "LIVE" in up("NTT DATA Opens Bengaluru 4 Data Center, Adds 100 MW Hyperscale Capacity.")
    assert "LIVE" in up("YTL Power yesterday announced the completion of its AI data centre.")
    assert "SITE" in up("HyperVault has secured 264 acres of land in Hyderabad to develop a campus.")
    assert "FINANCED" not in up("Princeton Digital Group seeks US$1.2 bil loan for Malaysian data centre.")
    assert not event_fits("POWER", "It is carrier neutral, interconnected with NTT's other data center locations.")


# ── Evidence Miner ──

def test_miner_finds_stage_language_for_the_project_only():
    mined = {e["layer"] for e in mine_evidence({"project_name": "JHB2", "developer": "AirTrunk", "events": []}, ARTICLE)}
    assert {"POWER", "BUILDING"} <= mined


def test_miner_ignores_future_tense():
    text = "Yotta said its new Navi Mumbai campus will be commissioned in 2027."
    assert mine_evidence({"project_name": "Yotta Navi Mumbai campus", "developer": "Yotta", "events": []}, text) == []


def test_project_sentences_split_headlines():
    text = "AdaniConneX opens its flagship campus in Chennai\n\nThe company said demand is strong."
    sents = project_sentences({"project_name": "Chennai 1", "developer": "AdaniConneX"}, text)
    assert sents and sents[0].startswith("AdaniConneX opens")


def test_gazetteer_picks_the_developer_nearest_the_project():
    text = "Vantage expanded in Kuala Lumpur. Separately, AirTrunk raised a loan for its JHB2 campus in Johor."
    assert gazetteer_developer(text, "JHB2 campus") == "AirTrunk"


def test_non_facility_names_are_rejected():
    assert NON_FACILITY.search("NTT DATA 900 MW Bloom fuel-cell capacity agreement")
    assert not NON_FACILITY.search("AirTrunk JHB2")


# ── Resolver ──

def _m(i, name, dev, cap=None, city=None, published=None, events=None):
    return {"id": i, "article_id": f"a{i}", "text_kind": "full", "published": published or datetime(2026, 1, i, tzinfo=timezone.utc),
            "data": {"project_name": name, "developer": dev, "city": city, "country": "Malaysia", "capacity_mw": cap, "events": events or []}}


def test_developer_aliases_and_facility_codes():
    assert canonical_developer("STTGDC India") == "STT GDC"
    assert canonical_developer("AirTrunk Pty Ltd") == "AirTrunk"
    assert facility_code("AirTrunk JHB2 hyperscale campus") == "JHB2"


def test_resolver_merges_same_project_different_names():
    ps = resolve([_m(1, "JHB2 hyperscale data centre", "AirTrunk", 150, "Kulai"),
                  _m(2, "AirTrunk's JHB2 campus", "AirTrunk Pty", None, "Johor Bahru"),
                  _m(3, "JHB2", None, 160)])
    assert len(ps) == 1 and len(ps[0]["mention_ids"]) == 3


def test_resolver_keeps_different_facility_codes_apart():
    ps = resolve([_m(1, "AirTrunk JHB1", "AirTrunk", 100), _m(2, "AirTrunk JHB2", "AirTrunk", 150)])
    assert len(ps) == 2


def test_resolver_keeps_conflicting_capacities_apart_without_a_code():
    ps = resolve([_m(1, "YTL Kulai campus", "YTL", 100, "Kulai"), _m(2, "YTL Kulai campus", "YTL", 500, "Kulai")])
    assert len(ps) == 2


# ── Geography ──

def test_places_and_country_inference():
    assert resolve_place("Sedenak Tech Park, Johor") == "Sedenak"
    assert resolve_place("Panvel") == "Navi Mumbai"
    assert infer_country("the RM2 billion campus in Johor") == "Malaysia"
    assert infer_country("a ₹5,000 crore investment") == "India"
    assert infer_country("a campus in Jakarta, Indonesia") is None


# ── Scorer ──

def _p(**kw):
    base = {"events": [], "article_ids": ["a1", "a2"], "text_kinds": ["full"], "last_seen": datetime.now(timezone.utc),
            "capacity_mw": 100, "target_year": None, "power_partner": None, "capacities": [], "target_years": []}
    return {**base, **kw}


def test_more_evidence_means_higher_reality():
    announced, _ = S.reality(_p(events=[{"layer": "ANNOUNCED"}]))
    powered, _ = S.reality(_p(events=[{"layer": "POWER"}]))
    live, _ = S.reality(_p(events=[{"layer": "LIVE"}]))
    assert announced < powered < live


def test_cancelled_and_negative_signals():
    assert S.reality(_p(events=[{"layer": "BUILDING"}, {"layer": "CANCELLED"}]))[0] == 0.03
    delayed, br = S.reality(_p(events=[{"layer": "POWER"}, {"layer": "DELAYED"}]))
    assert delayed < S.reality(_p(events=[{"layer": "POWER"}]))[0]
    assert any(b["term"] == "Delayed" for b in br)


def test_breakdown_explains_every_adjustment():
    _, br = S.reality(_p(events=[{"layer": "SITE"}], article_ids=["a1"], text_kinds=["summary"]))
    terms = {b["term"] for b in br}
    assert {"Single source", "Headline-only evidence"} <= terms


def test_weakest_assumption_is_power_for_an_announcement():
    w = S.weakest_assumption(_p(events=[{"layer": "ANNOUNCED"}]))
    assert "power" in w["assumption"].lower() and w["uplift"] > 0


def test_anomalies_capacity_cut_and_date_slip():
    d1, d2 = datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)
    an = S.anomalies(_p(capacities=[{"mw": 300, "basis": "IT", "published": d1}, {"mw": 150, "basis": "IT", "published": d2}],
                        target_years=[(d1, 2026), (d2, 2028)]))
    kinds = {a["kind"] for a in an}
    assert {"capacity_conflict", "date_slip"} <= kinds
    assert next(a for a in an if a["kind"] == "capacity_conflict")["severity"] == "high"  # a cut, not a raise


def test_who_to_call_prefers_open_projects_in_the_window():
    now = datetime.now(timezone.utc)
    open_p = _p(events=[{"layer": "APPROVED"}], target_year=now.year + 1)
    taken = _p(events=[{"layer": "APPROVED"}], target_year=now.year + 1, power_partner="TNB")
    s1, s2 = S.reality(open_p)[0], S.reality(taken)[0]
    assert S.who_to_call(open_p, s1)["power"]["priority"] > S.who_to_call(taken, s2)["power"]["priority"]


def test_calibration_report():
    projects = [{"name": "a", "reality_score": 0.9}, {"name": "b", "reality_score": 0.2}]
    r = S.calibrate(projects, {"a": True, "b": False})
    assert r["n"] == 2 and r["brier"] < 0.05


# ── Scouts ──

def test_relevance_filter_and_title_normalisation():
    assert is_relevant("YTL to build 500MW data centre in Kulai", "")
    assert not is_relevant("Johor property prices rise", "Housing demand grows.")
    assert normalise_title("YTL expands Kulai campus - The Star") == normalise_title("YTL expands Kulai campus")


def test_power_partner_named_from_verified_power_quote():
    """Headline-only evidence leaves the LLM's power_partner empty; the verified quote still names the utility."""
    from app.phantom.resolve import power_partner_from_evidence
    assert power_partner_from_evidence([{"quote": "DayOne signs 1.5GW renewable supply deal with TNB in Malaysia"}]) == "TNB"
    assert power_partner_from_evidence([{"quote": "Signed a power purchase agreement with Tata Power for 100 MW."}]) == "Tata Power"
    assert power_partner_from_evidence([{"quote": "Construction of a 220kV substation began."}]) is None
    ps = resolve([_m(1, "DayOne Selangor campus", "DayOne", 1500, "Selangor",
                     events=[{"layer": "POWER", "quote": "DayOne signs 1.5GW renewable supply deal with TNB in Malaysia"}])])
    assert ps[0]["power_partner"] == "TNB"
