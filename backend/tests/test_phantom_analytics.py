"""Phantom Hunter analytics pack — Excel/CSV export, SQL report, analysis findings."""

import io
import re
from datetime import datetime, timezone

import pytest
from openpyxl import load_workbook

from app.phantom.export import build_xlsx, tables, to_csv
from app.phantom.models import PhAnomaly, PhArticle, PhEvidence, PhProject
from app.phantom.sql_report import SQL_FILE, parse_queries, run


@pytest.fixture
def phantom_data(db_session):
    d = datetime(2026, 9, 1, tzinfo=timezone.utc)
    a = PhArticle(url="https://example.com/a", title="DayOne signs TNB deal", source="DCD", feed="bing",
                  published_at=d, text="x", text_kind="summary", relevant=True, extracted=True)
    db_session.add(a)
    db_session.flush()
    rows = [("DayOne Selangor", "DayOne", "Selangor", "Malaysia", 1500, 0.71, 3, "TNB", 2),
            ("Yotta Navi Mumbai", "Yotta", "Maharashtra", "India", 300, 0.2, 0, None, 1),
            ("Unsized campus", "CtrlS", "Telangana", "India", None, 0.98, 5, None, 3)]
    for name, dev, state, country, cap, score, stage, partner, n in rows:
        p = PhProject(name=name, developer=dev, state=state, country=country, capacity_mw=cap, reality_score=score,
                      stage=stage, power_partner=partner, n_sources=n, first_seen=d, last_seen=d,
                      score_breakdown=[{"term": "Evidence layer", "delta": None, "value": 0.75, "why": "prior"}],
                      call_segments={"power": {"priority": 40, "reasons": ["no energy partner named yet"]}})
        db_session.add(p)
        db_session.flush()
        db_session.add(PhEvidence(project_id=p.id, article_id=a.id, layer="POWER", quote="signs deal with TNB", event_date=d, verified=True))
    db_session.add(PhAnomaly(project_id=p.id, kind="stale", severity="low", message="quiet"))
    db_session.commit()
    return db_session


def test_tables_compute_reality_and_phantom_mw(phantom_data):
    t = tables(phantom_data)
    p = {r["name"]: r for r in t["projects"]}
    assert p["DayOne Selangor"]["reality_mw"] == 1065.0 and p["DayOne Selangor"]["phantom_mw"] == 435.0
    assert p["Unsized campus"]["reality_mw"] is None          # no capacity → never invented
    assert p["Yotta Navi Mumbai"]["score_band"].startswith("Phantom risk")
    assert {"projects", "who_to_call", "evidence", "anomalies", "score_terms", "articles"} <= set(t)
    assert "text" not in t["articles"][0]                      # article bodies are not redistributed
    assert t["evidence"][0]["source"] == "DCD"


def test_xlsx_formulas_point_at_the_right_columns(phantom_data):
    wb = load_workbook(io.BytesIO(build_xlsx(tables(phantom_data))))
    assert {"Summary", "Analysis", "Projects", "Who to call", "Evidence"} <= set(wb.sheetnames)
    headers = {c.column_letter: c.value for c in wb["Projects"][1]}

    def cols_in(formula):
        return {headers[m] for m in re.findall(r"Projects!\$([A-Z]+)\$2", formula)}

    summary = {r[0].value: r[1].value for r in wb["Summary"].iter_rows(min_row=4, max_row=11)}
    assert cols_in(summary["Announced capacity (MW)"]) == {"capacity_mw"}
    assert cols_in(summary["Reality-weighted capacity (MW)"]) == {"reality_mw"}
    assert cols_in(summary["Projects with a named power partner"]) == {"power_partner"}
    an = wb["Analysis"]
    assert an["A4"].value == "ANNOUNCED" and cols_in(an["C4"].value) == {"capacity_mw", "stage_name"}
    assert len(an._charts) == 2


def test_csv_is_plain_and_ordered(phantom_data):
    csv_text = to_csv(tables(phantom_data)["projects"])
    assert csv_text.splitlines()[0].startswith("project_id,name,developer,country")
    assert csv_text.count("\n") == 4


def test_export_endpoints(client, phantom_data):
    r = client.get("/api/v1/phantom/export.xlsx")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats")
    r = client.get("/api/v1/phantom/export/projects.csv")
    assert r.status_code == 200 and "DayOne Selangor" in r.text
    assert client.get("/api/v1/phantom/export/users.csv").status_code == 404   # only whitelisted tables


def test_every_sql_query_runs_against_the_schema(phantom_data):
    queries = parse_queries(SQL_FILE.read_text(encoding="utf-8"))
    assert len(queries) >= 10 and all(q for _, q, _ in queries)        # every block states its business question
    conn = phantom_data.connection()
    results = {name: run(conn, sql) for name, _, sql in queries}
    cols, rows = results["pipeline_headline"]
    head = dict(zip(cols, rows[0]))
    assert head["announced_mw"] == 1800 and head["reality_mw"] == round(1500 * 0.71 + 300 * 0.2)


def test_analysis_findings_are_computed(phantom_data):
    from app.phantom.analysis import analyse, report
    f = analyse(tables(phantom_data))
    assert f["announced"] == 1800 and f["n_capped"] == 2
    assert f["coverage"]["1"][0] == 1
    text = report(f, {})
    assert "1.8 GW announced" in text
