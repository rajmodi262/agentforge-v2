"""Generate a Power BI Project (.pbip) for Phantom Hunter — no Power BI needed to build it.

A .pbix is a binary only Power BI Desktop can write. A .pbip is Microsoft's text-based
equivalent: Power BI Desktop opens it fully built (data, relationships, measures, report
page), and File → Save as → .pbix converts it.

    python analytics/powerbi/build_pbip.py [OUTPUT_FOLDER]

Output: OUTPUT_FOLDER/PhantomHunter.pbip (+ .SemanticModel, .Report, data/*.csv).
Measures come from measures.dax; data from analytics/data/*.csv. Standard library only.
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
    return "\n".join([
        "let",
        f'    Source = Csv.Document(File.Contents(DataFolder & "\\{table}.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),',
        "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),",
        '    Blanks = Table.ReplaceValue(Promoted, "", null, Replacer.ReplaceValue, Table.ColumnNames(Promoted)),  // empty cell → blank, so ISBLANK works',
        f'    Typed = Table.TransformColumnTypes(Blanks, {{{types}}}, "en-US")',
        "in",
        "    Typed",
    ])


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
    folder = str(data_folder)
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
                             "expression": f'"{folder}" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]'}],
            "annotations": [{"name": "PBI_QueryOrder", "value": json.dumps(["DataFolder", *SCHEMA])},
                            {"name": "__PBI_TimeIntelligenceEnabled", "value": "0"}],
        },
    }


# ─────────────── report ───────────────

def _field(kind: str, table: str, prop: str) -> dict:
    alias = table[0]
    return {kind: {"Expression": {"SourceRef": {"Source": alias}}, "Property": prop}, "Name": f"{table}.{prop}"}


def visual(vtype: str, x, y, w, h, roles: dict, title: str = "", order_by=None) -> dict:
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
    if title:
        single["vcObjects"] = {"title": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}},
                                                          "text": {"expr": {"Literal": {"Value": f"'{title}'"}}}}}]}
    name = uuid.uuid4().hex[:20]
    cfg = {"name": name, "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": 0, "width": w, "height": h}}], "singleVisual": single}
    return {"x": x, "y": y, "z": 0, "width": w, "height": h, "config": json.dumps(cfg), "filters": "[]"}


def report() -> dict:
    M = lambda n: ("Measure", HOME, n)  # noqa: E731
    C = lambda t, c: ("Column", t, c)  # noqa: E731
    vs = [
        visual("card", 20, 10, 1240, 60, {"Values": [M("Headline")]}),
        visual("card", 20, 80, 300, 110, {"Values": [M("Announced MW")]}, "Announced MW"),
        visual("card", 335, 80, 300, 110, {"Values": [M("Reality MW")]}, "Reality-weighted MW"),
        visual("card", 650, 80, 300, 110, {"Values": [M("Phantom MW")]}, "Phantom MW"),
        visual("card", 965, 80, 295, 110, {"Values": [M("Reality Share")]}, "Reality share"),
        visual("clusteredBarChart", 20, 205, 620, 300, {"Category": [C("projects", "state")], "Y": [M("Announced MW"), M("Reality MW")]},
               "Announced vs reality-weighted MW by state", order_by=M("Announced MW")),
        visual("funnel", 655, 205, 300, 300, {"Category": [C("projects", "stage_name")], "Y": [M("Projects")]}, "Evidence ladder — projects by stage"),
        visual("slicer", 970, 205, 290, 140, {"Values": [C("projects", "country")]}, "Country"),
        visual("slicer", 970, 355, 290, 150, {"Values": [C("projects", "score_band")]}, "Reality band"),
        visual("tableEx", 20, 515, 1240, 195, {"Values": [C("who_to_call", "project"), C("who_to_call", "segment"),
                                                          C("who_to_call", "priority"), C("who_to_call", "reasons")]},
               "Who to call this month", order_by=C("who_to_call", "priority")),
    ]
    section = {"name": "ReportSection" + uuid.uuid4().hex[:12], "displayName": "Pipeline reality", "displayOption": 1,
               "width": 1280, "height": 720, "config": "{}", "filters": "[]", "visualContainers": vs}
    cfg = {"version": "5.59", "themeCollection": {}, "activeSectionIndex": 0, "defaultDrillFilterOtherVisuals": True,
           "settings": {"useStylableVisualContainerHeader": True}}
    return {"config": json.dumps(cfg), "layoutOptimization": 0, "sections": [section]}


def platform(kind: str) -> dict:
    return {"$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
            "metadata": {"type": kind, "displayName": NAME}, "config": {"version": "2.0", "logicalId": str(uuid.uuid4())}}


def build(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    data = out / "data"
    data.mkdir(exist_ok=True)
    for t in SCHEMA:
        shutil.copy2(DATA / f"{t}.csv", data / f"{t}.csv")
    shutil.copy2(HERE / "PhantomHunter_theme.json", out / "PhantomHunter_theme.json")
    sm, rp = out / f"{NAME}.SemanticModel", out / f"{NAME}.Report"
    sm.mkdir(exist_ok=True)
    rp.mkdir(exist_ok=True)
    w = lambda p, obj: p.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")  # noqa: E731
    w(sm / "model.bim", model(data.resolve()))
    w(sm / "definition.pbism", {"version": "1.0", "settings": {}})
    w(sm / ".platform", platform("SemanticModel"))
    w(rp / "report.json", report())
    w(rp / "definition.pbir", {"version": "1.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}, "byConnection": None}})
    w(rp / ".platform", platform("Report"))
    pbip = out / f"{NAME}.pbip"
    w(pbip, {"version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}], "settings": {"enableAutoRecovery": True}})
    return pbip


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "pbip"
    print(f"built {build(target)}")
