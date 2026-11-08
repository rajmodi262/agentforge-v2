"""Business exports — the same data the dashboard shows, in the tools analysts actually use.

One function, `tables()`, flattens the database into a small **star schema**:

    projects (one row per project)  ◄── who_to_call, evidence, anomalies, score_terms
    articles (one row per source article, no body text)

Everything else is built from it, so Excel, Google Sheets, Power BI and the SQL
report can never disagree with each other or with the dashboard:

* `build_xlsx()`  → a formatted Excel workbook: KPI summary, Excel tables with filters,
                    a colour scale on the reality score, live SUMIFS/COUNTIFS analysis
                    (works unchanged in Google Sheets) and native Excel charts.
* `write_csvs()`  → one UTF-8 CSV per table (Power BI "Folder" source, Sheets import).

CLI:  python -m app.phantom.export            → analytics/PhantomHunter.xlsx + analytics/data/*.csv
"""

from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.database import SessionLocal
from app.phantom.models import PhAnomaly, PhArticle, PhEvidence, PhProject
from app.phantom.score import LAYERS

ROOT = Path(__file__).resolve().parents[3]          # repo root
ANALYTICS = ROOT / "analytics"

SEGMENT_NAMES = {"power": "Power & IPPs", "electrical": "Electrical equipment", "cooling": "Cooling & thermal"}


def score_band(score: Optional[float]) -> str:
    if score is None:
        return "unscored"
    return "Likely (≥70%)" if score >= 0.7 else "At risk (45–70%)" if score >= 0.45 else "Phantom risk (<45%)"


def _d(dt) -> Optional[str]:
    return dt.date().isoformat() if dt else None


def tables(db=None) -> Dict[str, List[Dict[str, Any]]]:
    """Flatten the Phantom database into export tables (list of row dicts each)."""
    own = db is None
    db = db or SessionLocal()
    try:
        projects = db.query(PhProject).all()
        arts = {a.id: a for a in db.query(PhArticle).all()}
        out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for p in projects:
            pid = str(p.id)
            score = p.reality_score or 0.0
            cap = p.capacity_mw
            out["projects"].append({
                "project_id": pid, "name": p.name, "developer": p.developer, "country": p.country,
                "state": p.state, "city": p.city, "lat": p.lat, "lon": p.lon,
                "capacity_mw": cap, "capacity_basis": p.capacity_basis,
                "reality_score": round(score, 3), "reality_mw": round(cap * score, 1) if cap else None,
                "phantom_mw": round(cap * (1 - score), 1) if cap else None, "score_band": score_band(p.reality_score),
                "stage": p.stage, "stage_name": LAYERS[p.stage or 0], "target_year": p.target_year,
                "power_partner": p.power_partner, "cooling": p.cooling, "ai_density": bool(p.ai_density),
                "n_sources": p.n_sources, "first_seen": _d(p.first_seen), "last_seen": _d(p.last_seen),
                "weakest_assumption": p.weakest_assumption,
            })
            for key, seg in (p.call_segments or {}).items():
                out["who_to_call"].append({"project_id": pid, "project": p.name, "segment": SEGMENT_NAMES.get(key, key),
                                           "priority": seg.get("priority"), "reasons": " · ".join(seg.get("reasons") or [])})
            for b in p.score_breakdown or []:
                out["score_terms"].append({"project_id": pid, "term": b.get("term"), "logit_change": b.get("delta"), "prior": b.get("value"),
                                           "why": b.get("why")})
        for e in db.query(PhEvidence).all():
            a = arts.get(e.article_id)
            out["evidence"].append({"project_id": str(e.project_id), "layer": e.layer, "quote": e.quote,
                                    "event_date": _d(e.event_date), "source": a.source if a else None,
                                    "url": a.url if a else None, "text_kind": a.text_kind if a else None})
        for an in db.query(PhAnomaly).all():
            out["anomalies"].append({"project_id": str(an.project_id), "kind": an.kind, "severity": an.severity, "message": an.message})
        for a in arts.values():  # metadata only — article bodies are not redistributed
            out["articles"].append({"article_id": str(a.id), "title": a.title, "source": a.source, "feed": a.feed,
                                    "published": _d(a.published_at), "text_kind": a.text_kind,
                                    "relevant": a.relevant, "extracted": a.extracted, "url": a.url})
        for k in ("projects", "who_to_call", "score_terms", "evidence", "anomalies", "articles"):
            out.setdefault(k, [])
        out["projects"].sort(key=lambda r: -(r["capacity_mw"] or 0))
        out["who_to_call"].sort(key=lambda r: -(r["priority"] or 0))
        return dict(out)
    finally:
        if own:
            db.close()


def to_csv(rows: List[Dict[str, Any]]) -> str:
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return buf.getvalue()


def write_csvs(folder: Path, data: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> List[Path]:
    data = data or tables()
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, rows in data.items():
        p = folder / f"{name}.csv"
        p.write_text(to_csv(rows), encoding="utf-8-sig")  # BOM so Excel opens UTF-8 (₹, –) correctly
        paths.append(p)
    return paths


# ───────────────────────── Excel workbook ─────────────────────────

def build_xlsx(data: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> bytes:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference
    from openpyxl.formatting.rule import ColorScaleRule
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    data = data or tables()
    wb = Workbook()
    head = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="4C1D95")
    title = Font(bold=True, size=16, color="4C1D95")

    def sheet(name: str, rows: List[Dict[str, Any]], widths: Optional[Dict[str, int]] = None):
        ws = wb.create_sheet(name)
        if not rows:
            ws.append(["(no rows)"])
            return ws
        cols = list(rows[0].keys())
        ws.append(cols)
        for r in rows:
            ws.append([r[c] for c in cols])
        for i, c in enumerate(cols, 1):
            ws.column_dimensions[get_column_letter(i)].width = (widths or {}).get(c, min(45, max(10, len(c) + 4)))
        tab = Table(displayName=f"t_{name.replace(' ', '_')}", ref=f"A1:{get_column_letter(len(cols))}{len(rows) + 1}")
        tab.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        ws.add_table(tab)
        ws.freeze_panes = "B2"
        return ws

    # 1. Summary — KPIs as live formulas over the Projects table
    ws = wb.active
    ws.title = "Summary"
    ws["A1"], ws["A1"].font = "Phantom Hunter — India & Malaysia data-centre pipeline", title
    ws["A2"] = f"Exported {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · every number below is a live formula over the Projects sheet"
    ws["A2"].font = Font(italic=True, color="666666")
    n = len(data["projects"]) + 1
    P = lambda col: f"Projects!${col}$2:${col}${n}"  # noqa: E731
    cols = {c: get_column_letter(i + 1) for i, c in enumerate(data["projects"][0].keys())} if data["projects"] else {}
    kpis = [
        ("Projects resolved", f"=COUNTA({P(cols['project_id'])})", "0"),
        ("Announced capacity (MW)", f"=SUM({P(cols['capacity_mw'])})", "#,##0"),
        ("Reality-weighted capacity (MW)", f"=SUM({P(cols['reality_mw'])})", "#,##0"),
        ("Phantom capacity (MW)", f"=SUM({P(cols['phantom_mw'])})", "#,##0"),
        ("Reality share of announced", "=B6/B5", "0%"),
        ("Average reality score", f"=AVERAGE({P(cols['reality_score'])})", "0%"),
        ("Projects with a named power partner", f"=COUNTIF({P(cols['power_partner'])},\"?*\")", "0"),
        ("Single-source projects", f"=COUNTIF({P(cols['n_sources'])},1)", "0"),
    ] if cols else []
    for i, (label, formula, fmt) in enumerate(kpis, start=4):
        ws.cell(i, 1, label).font = Font(bold=True)
        c = ws.cell(i, 2, formula)
        c.number_format = fmt
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 38, 18
    ws["A13"] = "Sheets: Projects · Who to call · Evidence · Anomalies · Score terms · Articles · Analysis (live SUMIFS/COUNTIFS + charts)"
    ws["A13"].font = Font(color="666666")

    # 2. Data sheets
    pw = sheet("Projects", data["projects"], {"name": 42, "developer": 20, "weakest_assumption": 60, "project_id": 12})
    if data["projects"]:
        L = cols["reality_score"]
        pw.conditional_formatting.add(f"{L}2:{L}{n}", ColorScaleRule(start_type="num", start_value=0, start_color="F87171",
                                                                     mid_type="num", mid_value=0.5, mid_color="FBBF24",
                                                                     end_type="num", end_value=1, end_color="34D399"))
        for c in ("reality_score",):
            for row in pw.iter_rows(min_row=2, min_col=pw[f"{cols[c]}1"].column, max_col=pw[f"{cols[c]}1"].column):
                row[0].number_format = "0%"
    sheet("Who to call", data["who_to_call"], {"project": 42, "segment": 22, "reasons": 80})
    ev = sheet("Evidence", data["evidence"], {"quote": 90, "url": 50, "source": 24})
    for row in ev.iter_rows(min_row=2, min_col=3, max_col=3):
        row[0].alignment = Alignment(wrap_text=False)
    sheet("Anomalies", data["anomalies"], {"message": 90})
    sheet("Score terms", data["score_terms"], {"term": 34, "why": 80})
    sheet("Articles", data["articles"], {"title": 70, "url": 50, "source": 26})

    # 3. Analysis — live formulas (identical syntax in Excel and Google Sheets) + native charts
    an = wb.create_sheet("Analysis", 1)
    an["A1"], an["A1"].font = "Analysis — live formulas over the Projects sheet", title
    if data["projects"]:
        cap, rmw, ctry, stg, st = (P(cols[k]) for k in ("capacity_mw", "reality_mw", "country", "stage_name", "state"))
        an.append([])
        an.append(["Stage", "Projects", "Announced MW", "Reality MW"])
        for c in an[3]:
            c.font, c.fill = head, head_fill
        for i, layer in enumerate(LAYERS, start=4):
            an.append([layer, f"=COUNTIF({stg},A{i})", f"=SUMIFS({cap},{stg},A{i})", f"=SUMIFS({rmw},{stg},A{i})"])
        an.append([])
        r0 = 4 + len(LAYERS) + 1
        an.cell(r0, 1, "Country").font, an.cell(r0, 2, "Projects").font = Font(bold=True), Font(bold=True)
        an.cell(r0, 3, "Announced MW").font, an.cell(r0, 4, "Reality MW").font, an.cell(r0, 5, "Reality share").font = (Font(bold=True),) * 3
        for j, country in enumerate(sorted({p["country"] for p in data["projects"] if p["country"]}), start=r0 + 1):
            an.cell(j, 1, country)
            an.cell(j, 2, f"=COUNTIF({ctry},A{j})")
            an.cell(j, 3, f"=SUMIFS({cap},{ctry},A{j})")
            an.cell(j, 4, f"=SUMIFS({rmw},{ctry},A{j})")
            an.cell(j, 5, f"=IF(C{j}=0,\"\",D{j}/C{j})").number_format = "0%"
        r1 = r0 + 4
        an.cell(r1, 1, "State / region (top 10 by announced MW)").font = Font(bold=True)
        an.cell(r1 + 1, 1, "State").font, an.cell(r1 + 1, 2, "Projects").font = Font(bold=True), Font(bold=True)
        an.cell(r1 + 1, 3, "Announced MW").font, an.cell(r1 + 1, 4, "Reality MW").font = Font(bold=True), Font(bold=True)
        by_state = Counter()
        for p in data["projects"]:
            if p["state"]:
                by_state[p["state"]] += p["capacity_mw"] or 0
        for j, (state, _) in enumerate(by_state.most_common(10), start=r1 + 2):
            an.cell(j, 1, state)
            an.cell(j, 2, f"=COUNTIF({st},A{j})")
            an.cell(j, 3, f"=SUMIFS({cap},{st},A{j})")
            an.cell(j, 4, f"=SUMIFS({rmw},{st},A{j})")
        for col in "BCD":
            for row in an[f"{col}4:{col}{r1 + 12}"]:
                if row[0].number_format != "0%":
                    row[0].number_format = "#,##0"
        an.column_dimensions["A"].width = 30
        for col in "BCDE":
            an.column_dimensions[col].width = 16

        ch = BarChart()
        ch.title, ch.y_axis.title = "Announced vs reality-weighted MW by stage", "MW"
        ch.add_data(Reference(an, min_col=3, max_col=4, min_row=3, max_row=3 + len(LAYERS)), titles_from_data=True)
        ch.set_categories(Reference(an, min_col=1, min_row=4, max_row=3 + len(LAYERS)))
        ch.height, ch.width = 8, 16
        an.add_chart(ch, "G3")
        ch2 = BarChart()
        ch2.type, ch2.title = "bar", "Announced vs reality MW — top states"
        ch2.add_data(Reference(an, min_col=3, max_col=4, min_row=r1 + 1, max_row=r1 + 11), titles_from_data=True)
        ch2.set_categories(Reference(an, min_col=1, min_row=r1 + 2, max_row=r1 + 11))
        ch2.height, ch2.width = 9, 16
        an.add_chart(ch2, "G20")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def main():
    data = tables()
    ANALYTICS.mkdir(exist_ok=True)
    xlsx = ANALYTICS / "PhantomHunter.xlsx"
    xlsx.write_bytes(build_xlsx(data))
    paths = write_csvs(ANALYTICS / "data", data)
    print(f"wrote {xlsx.relative_to(ROOT)} and {len(paths)} CSVs: " + ", ".join(f"{p.stem} ({len(data[p.stem])})" for p in paths))


if __name__ == "__main__":
    main()
