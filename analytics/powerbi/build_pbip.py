"""Generate a Power BI Project (.pbip) for Phantom Hunter — no Power BI needed to build it.

A .pbix is a binary only Power BI Desktop can write. A .pbip is Microsoft's text-based
equivalent: Power BI Desktop opens it fully built (data, relationships, measures, a dark
"Phantom" theme and two report pages), and File → Save as → .pbix converts it.

    python analytics/powerbi/build_pbip.py [OUTPUT_FOLDER]

Output: OUTPUT_FOLDER/PhantomHunter.pbip (+ .SemanticModel, .Report, data/*.csv).
Measures come from measures.dax; data from analytics/data/*.csv. Standard library only.
After opening: Home → Refresh (a .pbip stores no data), then Save as .pbix.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
NAME = "PhantomHunter"
HOME = "projects"  # table that holds the measures

# column → (TMSL dataType, M type)
T, D, I, DT = ("string", "type text"), ("double", "type number"), ("int64", "Int64.Type"), ("dateTime", "type date")
SCHEMA = {
    "projects": {"project_id": T, "name": T, "developer": T, "country": T, "state": T, "city": T, "lat": D, "lon": D,
                 "capacity_mw": D, "capacity_basis": T, "reality_score": D, "reality_mw": D, "phantom_mw": D,
                 "score_band": T, "stage": I, "stage_name": T, "target_year": I, "power_partner": T, "cooling": T,
                 "ai_density": T, "n_sources": I, "first_seen": DT, "last_seen": DT, "weakest_assumption": T},
    "who_to_call": {"project_id": T, "project": T, "segment": T, "priority": I, "reasons": T},
    "evidence": {"project_id": T, "layer": T, "quote": T, "event_date": DT, "source": T, "url": T, "text_kind": T},
    "anomalies": {"project_id": T, "kind": T, "severity": T, "message": T},
    "score_terms": {"project_id": T, "term": T, "logit_change": D, "prior": D, "why": T},
}
FORMATS = {"capacity_mw": "#,0", "reality_mw": "#,0", "phantom_mw": "#,0", "reality_score": "0%", "lat": "0.0000", "lon": "0.0000"}
CATEGORY = {"lat": "Latitude", "lon": "Longitude", "state": "StateOrProvince", "city": "City", "country": "Country"}
MEASURE_FORMATS = {"Reality Share": "0%", "Avg Reality Score": "0%", "Weighted Reality Score": "0%",
                   "Single Source Share": "0%", "Headline-only Evidence Share": "0%"}


def parse_dax(path: Path):
    """measures.dax blocks `Name = expression` separated by blank lines; // comments ignored."""
    out = []
    text = "\n".join(l for l in path.read_text(encoding="utf-8").splitlines() if not l.strip().startswith("//"))
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        m = re.match(r"^([^=\n]+?)\s*=\s*(.+)$", block, re.S)
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
    return out


def m_query(table: str) -> str:
    types = ", ".join(f'{{"{c}", {mt}}}' for c, (_, mt) in SCHEMA[table].items())
    lines = [
        "let",
        f'    Source = Csv.Document(File.Contents(DataFolder & "\\{table}.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),',
        "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),",
        '    Blanks = Table.ReplaceValue(Promoted, "", null, Replacer.ReplaceValue, Table.ColumnNames(Promoted)),  // empty cell → blank, so ISBLANK works',
        f'    Typed = Table.TransformColumnTypes(Blanks, {{{types}}}, "en-US")',
    ]
    last = "Typed"
    if table == "projects":  # readable axis label instead of "(Blank)"
        lines[-1] += ","
        lines.append('    Placed = Table.ReplaceValue(Typed, null, "Place not stated", Replacer.ReplaceValue, {"state"})')
        last = "Placed"
    return "\n".join(lines + ["in", f"    {last}"])


def model(data_folder: Path) -> dict:
    tables = []
    for t, cols in SCHEMA.items():
        columns = []
        for c, (dtype, _) in cols.items():
            col = {"name": c, "dataType": dtype, "sourceColumn": c,
                   "summarizeBy": "sum" if c in ("capacity_mw", "reality_mw", "phantom_mw") else "none"}
            if c in FORMATS:
                col["formatString"] = FORMATS[c]
            if dtype == "dateTime":
                col["formatString"] = "yyyy-mm-dd"
            if c in CATEGORY:
                col["dataCategory"] = CATEGORY[c]
            if t == "projects" and c == "stage_name":
                col["sortByColumn"] = "stage"  # funnel/axes in ladder order, not alphabetical
            if c == "project_id" and t != "projects":
                col["isHidden"] = True
            columns.append(col)
        table = {"name": t, "columns": columns,
                 "partitions": [{"name": t, "mode": "import", "source": {"type": "m", "expression": m_query(t)}}]}
        if t == HOME:
            table["measures"] = [{"name": n, "expression": e, **({"formatString": MEASURE_FORMATS[n]} if n in MEASURE_FORMATS
                                                                 else {"formatString": "#,0"} if n.endswith("MW") or n.endswith("Projects") or n == "Projects" else {})}
                                 for n, e in parse_dax(HERE / "measures.dax")]
        tables.append(table)
    rels = [{"name": f"{t}_to_projects", "fromTable": t, "fromColumn": "project_id", "toTable": "projects", "toColumn": "project_id"}
            for t in SCHEMA if t != "projects"]
    return {
        "compatibilityLevel": 1567,
        "model": {
            "culture": "en-US",
            "dataAccessOptions": {"legacyRedirects": True, "returnErrorValuesAsNull": True},
            "defaultPowerBIDataSourceVersion": "powerBI_V3",
            "sourceQueryCulture": "en-US",
            "tables": tables,
            "relationships": rels,
            "expressions": [{"name": "DataFolder", "kind": "m",
                             "expression": f'"{data_folder}" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]'}],
            "annotations": [{"name": "PBI_QueryOrder", "value": json.dumps(["DataFolder", *SCHEMA])},
                            {"name": "__PBI_TimeIntelligenceEnabled", "value": "0"}],
        },
    }


# ─────────────── report: dark "Phantom" theme + two styled pages ───────────────

INK, PANEL, EDGE, MUTED = "#0B0A1F", "#16143A", "#2E2A5C", "#94A3B8"
VIOLET, CYAN, GREEN, RED, AMBER, PINK = "#A78BFA", "#22D3EE", "#34D399", "#F87171", "#FBBF24", "#F472B6"

THEME_FILE = "PhantomHunterDark.json"
THEME = {
    "name": "Phantom Hunter Dark",
    "dataColors": [VIOLET, GREEN, CYAN, AMBER, RED, PINK, "#818CF8", "#F97316"],
    "background": INK, "foreground": "#F1F5F9", "tableAccent": "#7C3AED",
    "good": GREEN, "neutral": AMBER, "bad": RED, "maximum": GREEN, "center": AMBER, "minimum": RED,
    "textClasses": {
        "callout": {"fontSize": 28, "fontFace": "Segoe UI Semibold", "color": "#FFFFFF"},
        "title": {"fontSize": 12, "fontFace": "Segoe UI Semibold", "color": "#E2E8F0"},
        "header": {"fontSize": 11, "fontFace": "Segoe UI Semibold", "color": "#E2E8F0"},
        "label": {"fontSize": 10, "fontFace": "Segoe UI", "color": "#CBD5E1"},
    },
    "visualStyles": {
        "page": {"*": {"background": [{"color": {"solid": {"color": INK}}, "transparency": 0}],
                       "outspace": [{"color": {"solid": {"color": INK}}, "transparency": 0}]}},
        "*": {"*": {
            "background": [{"show": True, "color": {"solid": {"color": PANEL}}, "transparency": 0}],
            "border": [{"show": True, "color": {"solid": {"color": EDGE}}, "radius": 14}],
            "dropShadow": [{"show": True, "color": {"solid": {"color": "#000000"}}, "position": "Outer", "preset": "BottomRight", "transparency": 55}],
            "title": [{"show": True, "fontColor": {"solid": {"color": "#E2E8F0"}}, "fontSize": 12, "fontFamily": "Segoe UI Semibold"}],
            "visualHeader": [{"foreground": {"solid": {"color": MUTED}}, "border": {"solid": {"color": PANEL}}, "background": {"solid": {"color": PANEL}}}],
            "categoryAxis": [{"labelColor": {"solid": {"color": "#CBD5E1"}}, "titleColor": {"solid": {"color": MUTED}}, "gridlineColor": {"solid": {"color": EDGE}}}],
            "valueAxis": [{"labelColor": {"solid": {"color": MUTED}}, "titleColor": {"solid": {"color": MUTED}}, "gridlineColor": {"solid": {"color": EDGE}}}],
            "legend": [{"labelColor": {"solid": {"color": "#E2E8F0"}}}],
            "labels": [{"color": {"solid": {"color": "#FFFFFF"}}}],
            "categoryLabels": [{"color": {"solid": {"color": MUTED}}}],
        }},
        "tableEx": {"*": {
            "columnHeaders": [{"fontColor": {"solid": {"color": "#FFFFFF"}}, "backColor": {"solid": {"color": "#4C1D95"}}, "fontSize": 10}],
            "values": [{"fontColorPrimary": {"solid": {"color": "#E2E8F0"}}, "backColorPrimary": {"solid": {"color": PANEL}},
                        "fontColorSecondary": {"solid": {"color": "#E2E8F0"}}, "backColorSecondary": {"solid": {"color": "#1E1B4B"}}, "fontSize": 10}],
            "grid": [{"gridHorizontal": True, "gridHorizontalColor": {"solid": {"color": EDGE}}, "gridVertical": False, "rowPadding": 4}],
        }},
        "slicer": {"*": {"items": [{"fontColor": {"solid": {"color": "#E2E8F0"}}, "fontSize": 11}],
                         "header": [{"fontColor": {"solid": {"color": VIOLET}}, "show": False}]}},
        "textbox": {"*": {"background": [{"show": False}], "border": [{"show": False}], "dropShadow": [{"show": False}]}},
    },
}


def lit(v) -> dict:
    """Power BI literal expression: strings quoted, numbers suffixed D, booleans bare."""
    if isinstance(v, bool):
        val = "true" if v else "false"
    elif isinstance(v, (int, float)):
        val = f"{v}D"
    else:
        val = f"'{v}'"
    return {"expr": {"Literal": {"Value": val}}}


def color(c: str) -> dict:
    return {"solid": {"color": lit(c)}}


def _field(kind: str, table: str, prop: str) -> dict:
    return {kind: {"Expression": {"SourceRef": {"Source": table[0]}}, "Property": prop}, "Name": f"{table}.{prop}"}


def _container(x, y, w, h, single: dict, z: int = 0) -> dict:
    cfg = {"name": uuid.uuid4().hex[:20], "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": z, "width": w, "height": h}}], "singleVisual": single}
    return {"x": x, "y": y, "z": z, "width": w, "height": h, "config": json.dumps(cfg), "filters": "[]"}


def visual(vtype: str, x, y, w, h, roles: dict, title: str = "", order_by=None, objects=None, vc=None) -> dict:
    """roles: {role: [(kind, table, prop), ...]} where kind is Column or Measure."""
    fields = [f for fs in roles.values() for f in fs]
    tables = sorted({t for _, t, _ in fields})
    query = {"Version": 2, "From": [{"Name": t[0], "Entity": t, "Type": 0} for t in tables],
             "Select": [_field(k, t, p) for k, t, p in fields]}
    if order_by:
        k, t, p = order_by
        query["OrderBy"] = [{"Direction": 2, "Expression": {k: {"Expression": {"SourceRef": {"Source": t[0]}}, "Property": p}}}]
    single = {"visualType": vtype,
              "projections": {r: [{"queryRef": f"{t}.{p}", **({"active": True} if vtype == "slicer" else {})} for _, t, p in fs]
                              for r, fs in roles.items()},
              "prototypeQuery": query, "drillFilterOtherVisuals": True}
    vco = {k: [dict(v[0])] for k, v in (vc or {}).items()}
    if title:
        props = vco.setdefault("title", [{"properties": {}}])[0].setdefault("properties", {})
        props.update({"show": lit(True), "text": lit(title)})
    if vco:
        single["vcObjects"] = vco
    if objects:
        single["objects"] = objects
    return _container(x, y, w, h, single)


def textbox(x, y, w, h, runs) -> dict:
    """runs: [(text, size_pt, hex_color, bold)] in one paragraph."""
    para = [{"textRuns": [{"value": t, "textStyle": {"fontSize": f"{sz}pt", "color": c, "fontWeight": "bold" if b else "normal",
                                                         "fontFamily": "Segoe UI Semibold" if b else "Segoe UI"}} for t, sz, c, b in runs]}]
    return _container(x, y, w, h, {"visualType": "textbox", "drillFilterOtherVisuals": True,
                                   "objects": {"general": [{"properties": {"paragraphs": para}}]},
                                   "vcObjects": {k: [{"properties": {"show": lit(False)}}] for k in ("background", "border", "dropShadow")}}, z=1)


def kpi(x, y, w, h, measure: str, title: str, accent: str) -> dict:
    """Card with a coloured value and a matching accent border."""
    return visual("card", x, y, w, h, {"Values": [("Measure", HOME, measure)]}, title,
                  objects={"labels": [{"properties": {"color": color(accent), "fontSize": lit(30), "labelDisplayUnits": lit(1)}}],  # 37,053 not 37K
                           "categoryLabels": [{"properties": {"show": lit(False)}}]},
                  vc={"border": [{"properties": {"show": lit(True), "color": color(accent), "radius": lit(14)}}],
                      "title": [{"properties": {"fontColor": color("#CBD5E1")}}]})


def series_colors(*pairs) -> list:
    return [{"properties": {"fill": color(c)}, "selector": {"metadata": f"{HOME}.{m}"}} for m, c in pairs]


def value_colors(column: str, pairs) -> list:
    """Colour each category value of projects[column] explicitly."""
    return [{"properties": {"fill": color(c)}, "selector": {"data": [{"scopeId": {"Comparison": {
        "ComparisonKind": 0, "Left": {"Column": {"Expression": {"SourceRef": {"Entity": "projects"}}, "Property": column}},
        "Right": {"Literal": {"Value": f"'{v}'"}}}}}]}} for v, c in pairs]


def country_colors(pairs) -> list:
    return value_colors("country", pairs)


# evidence ladder: cool → warm → green as a project gets more real
STAGE_COLORS = (("ANNOUNCED", "#A78BFA"), ("SITE", "#818CF8"), ("APPROVED", "#22D3EE"),
                ("POWER", "#FBBF24"), ("BUILDING", "#F97316"), ("LIVE", "#34D399"))


def col_widths(table: str, widths) -> list:
    return [{"properties": {"value": lit(w)}, "selector": {"metadata": f"{table}.{c}"}} for c, w in widths]


def _section(name: str, visuals: list) -> dict:
    return {"name": "ReportSection" + uuid.uuid4().hex[:12], "displayName": name, "displayOption": 1,
            "width": 1280, "height": 720, "config": "{}", "filters": "[]", "visualContainers": visuals}


M = lambda n: ("Measure", HOME, n)  # noqa: E731
C = lambda t, c: ("Column", t, c)  # noqa: E731
TOP_LEGEND = [{"properties": {"show": lit(True), "position": lit("Top")}}]
NO_FRAME = {k: [{"properties": {"show": lit(False)}}] for k in ("background", "border", "dropShadow")}


def page_pipeline() -> dict:
    return _section("Pipeline reality", [
        textbox(20, 8, 640, 52, [("👻 Phantom Hunter  ", 22, "#FFFFFF", True), ("India + Malaysia data-centre pipeline", 12, MUTED, False)]),
        visual("card", 660, 12, 600, 46, {"Values": [M("Headline")]},
               objects={"labels": [{"properties": {"color": color(CYAN), "fontSize": lit(17)}}],
                        "categoryLabels": [{"properties": {"show": lit(False)}}]}, vc=NO_FRAME),
        kpi(20, 70, 300, 105, "Announced MW", "📣 Announced MW", VIOLET),
        kpi(335, 70, 300, 105, "Reality MW", "✅ Reality-weighted MW", GREEN),
        kpi(650, 70, 300, 105, "Phantom MW", "👻 Phantom MW", RED),
        kpi(965, 70, 295, 105, "Reality Share", "🎯 Reality share", AMBER),
        visual("clusteredBarChart", 20, 188, 620, 316, {"Category": [C("projects", "state")], "Y": [M("Announced MW"), M("Reality MW")]},
               "📍 Announced vs likely MW by state", order_by=M("Announced MW"),
               objects={"dataPoint": series_colors(("Announced MW", "#7C3AED"), ("Reality MW", GREEN)), "legend": TOP_LEGEND}),
        visual("funnel", 655, 188, 300, 316, {"Category": [C("projects", "stage_name")], "Y": [M("Projects")]}, "🪜 Evidence ladder",
               objects={"dataPoint": [{"properties": {"showAllDataPoints": lit(True)}}] + value_colors("stage_name", STAGE_COLORS),
                        "labels": [{"properties": {"color": color("#FFFFFF"), "fontSize": lit(10), "labelPosition": lit("OutsideEnd")}}],
                        "categoryLabels": [{"properties": {"color": color("#E2E8F0"), "fontSize": lit(8)}}]}),
        visual("slicer", 970, 188, 290, 150, {"Values": [C("projects", "country")]}, "🌏 Country"),
        visual("slicer", 970, 352, 290, 152, {"Values": [C("projects", "score_band")]}, "🎚 Reality band"),
        visual("tableEx", 20, 516, 1240, 194, {"Values": [C("who_to_call", "project"), C("who_to_call", "segment"),
                                                          C("who_to_call", "priority"), C("who_to_call", "reasons")]},
               "📞 Who to call this month", order_by=C("who_to_call", "priority"),
               objects={"columnWidth": col_widths("who_to_call", (("project", 330), ("segment", 170), ("priority", 70), ("reasons", 620)))}),
    ])


def page_explorer() -> dict:
    return _section("Project explorer", [
        textbox(20, 8, 900, 52, [("🔎 Project explorer  ", 22, "#FFFFFF", True),
                                 ("size vs reality, and what each project still has to prove", 12, MUTED, False)]),
        kpi(20, 70, 240, 95, "Likely Projects", "🟢 Likely (≥70%)", GREEN),
        kpi(272, 70, 240, 95, "Phantom Risk Projects", "🔴 Phantom risk (<45%)", RED),
        kpi(524, 70, 240, 95, "Single Source Share", "📰 Single-source share", AMBER),
        kpi(776, 70, 240, 95, "Open Power Opportunities MW", "⚡ Open power MW", CYAN),
        kpi(1028, 70, 232, 95, "High Severity Anomalies", "🚨 High-severity anomalies", PINK),
        visual("scatterChart", 20, 178, 620, 330, {"Category": [C("projects", "name")], "Series": [C("projects", "country")],
                                                  "X": [M("Announced MW")], "Y": [M("Avg Reality Score")]},
               "🫧 Size vs reality score (each dot = a project)",
               objects={"dataPoint": country_colors((("India", VIOLET), ("Malaysia", CYAN))), "legend": TOP_LEGEND}),
        visual("columnChart", 655, 178, 605, 330, {"Category": [C("projects", "stage_name")], "Series": [C("projects", "country")], "Y": [M("Projects")]},
               "🏗 Projects by stage and country",
               objects={"dataPoint": country_colors((("India", VIOLET), ("Malaysia", CYAN))), "legend": TOP_LEGEND}),
        visual("tableEx", 20, 520, 1240, 190, {"Values": [C("projects", "name"), C("projects", "developer"), C("projects", "state"),
                                                          C("projects", "stage_name"), C("projects", "capacity_mw"), C("projects", "reality_score"),
                                                          C("projects", "weakest_assumption")]},
               "🧾 Projects and their weakest assumption", order_by=C("projects", "capacity_mw"),
               objects={"columnWidth": col_widths("projects", (("name", 300), ("developer", 140), ("state", 120), ("stage_name", 95),
                                                               ("capacity_mw", 95), ("reality_score", 90), ("weakest_assumption", 380)))}),
    ])


def report() -> dict:
    cfg = {"version": "5.59", "themeCollection": {"customTheme": {"name": THEME_FILE, "version": "5.59", "type": 1}},
           "activeSectionIndex": 0, "defaultDrillFilterOtherVisuals": True, "settings": {"useStylableVisualContainerHeader": True}}
    return {"config": json.dumps(cfg), "layoutOptimization": 0,
            "resourcePackages": [{"resourcePackage": {"name": "RegisteredResources", "type": 1, "disabled": False,
                                                      "items": [{"type": 202, "path": THEME_FILE, "name": THEME_FILE}]}}],
            "sections": [page_pipeline(), page_explorer()]}


def platform(kind: str) -> dict:
    return {"$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
            "metadata": {"type": kind, "displayName": NAME}, "config": {"version": "2.0", "logicalId": str(uuid.uuid4())}}


def build(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    data = out / "data"
    data.mkdir(exist_ok=True)
    for t in SCHEMA:
        shutil.copy2(DATA / f"{t}.csv", data / f"{t}.csv")
    sm, rp = out / f"{NAME}.SemanticModel", out / f"{NAME}.Report"
    res = rp / "StaticResources" / "RegisteredResources"
    sm.mkdir(exist_ok=True)
    res.mkdir(parents=True, exist_ok=True)
    w = lambda p, obj: p.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")  # noqa: E731
    w(sm / "model.bim", model(data.resolve()))
    w(sm / "definition.pbism", {"version": "1.0", "settings": {}})
    w(sm / ".platform", platform("SemanticModel"))
    w(rp / "report.json", report())
    w(res / THEME_FILE, THEME)
    w(out / THEME_FILE, THEME)  # standalone copy: View → Themes → Browse for themes
    w(rp / "definition.pbir", {"version": "1.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}, "byConnection": None}})
    w(rp / ".platform", platform("Report"))
    pbip = out / f"{NAME}.pbip"
    w(pbip, {"version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}], "settings": {"enableAutoRecovery": True}})
    return pbip


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "pbip"
    print(f"built {build(target)}")
