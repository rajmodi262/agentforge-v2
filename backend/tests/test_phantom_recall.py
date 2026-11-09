"""Recall matcher: developer groups, state, facility-code identity."""

from app.phantom.recall import REFERENCE, dev_key, load_reference, match, summarise


def _ref(**kw):
    base = {"ref_id": "R1", "developer": "AirTrunk", "project": "JHB2", "city": "Johor Bahru", "state": "Johor",
            "country": "Malaysia", "capacity_mw": "", "status": "announced", "year": "2026", "source": "t", "source_url": ""}
    return {**base, **kw}


def _p(name, dev, state, country="Malaysia"):
    return {"name": name, "developer": dev, "state": state, "country": country, "capacity_mw": 100, "stage_name": "SITE", "reality_score": 0.5}


def test_parent_and_jv_brands_are_one_developer():
    assert dev_key("Bharti Airtel") == dev_key("Nxtra")
    assert dev_key("GDS") == dev_key("DayOne")
    assert dev_key("TM Nxera") == dev_key("Telekom Malaysia")


def test_found_needs_same_developer_and_state():
    assert match([_ref()], [_p("AirTrunk Hyperscale Campus", "AirTrunk", "Johor")])[0]["verdict"] == "found"
    assert match([_ref()], [_p("AirTrunk KL", "AirTrunk", "Selangor")])[0]["verdict"] == "other_site"
    assert match([_ref()], [_p("AirTrunk", "AirTrunk", None)])[0]["verdict"] == "place_unknown"
    assert match([_ref()], [_p("YTL Kulai", "YTL", "Johor")])[0]["verdict"] == "missing"


def test_a_different_facility_code_is_a_different_site():
    rows = match([_ref(project="JHB2")], [_p("AirTrunk JHB1", "AirTrunk", "Johor")])
    assert rows[0]["verdict"] == "other_site"


def test_summary_and_pipeline_slice():
    rows = match([_ref(), _ref(ref_id="R2", developer="Open DC", status="operational", year="2019")],
                 [_p("AirTrunk Hyperscale Campus", "AirTrunk", "Johor")])
    s = summarise(rows)
    assert s["all"]["strict"] == 50.0 and s["pipeline"]["n"] == 1 and s["pipeline"]["strict"] == 100.0


def test_reference_list_is_sourced():
    ref = load_reference(REFERENCE)
    assert len(ref) >= 40 and all(r["source_url"].startswith("https://") for r in ref)
