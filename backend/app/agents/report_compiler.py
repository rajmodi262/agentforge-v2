"""AgentForge AI — Report Compiler Agent

Aggregates all 7 agent outputs into a structured report.
Generates PDF using ReportLab.
"""

import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class ReportCompiler:
    """Compiles all agent outputs into a downloadable report."""

    def compile_json(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Compile all agent outputs into a structured JSON report."""
        report = {
            "title": "AgentForge AI — Business Plan Report",
            "generated_by": "AgentForge AI Multi-Agent System",
            "sections": []
        }

        # The synthesized blueprint leads (it's the coherent, cross-checked result),
        # then the board's verdict, then each specialist's full analysis as appendix.
        section_map = {
            "final_blueprint_output": {"title": "1. Master Blueprint — Synthesized", "icon": "🏆"},
            "board_meeting_output": {"title": "2. Board Verdict & Debate", "icon": "🏛️"},
            "ceo_output": {"title": "3. Executive Summary (CEO Agent)", "icon": "🎯"},
            "research_output": {"title": "4. Market Research Report", "icon": "🔍"},
            "marketing_output": {"title": "5. Marketing Strategy", "icon": "📣"},
            "developer_output": {"title": "6. Technical Roadmap", "icon": "💻"},
            "finance_output": {"title": "7. Financial Projections", "icon": "💰"},
            "analytics_output": {"title": "8. KPI Framework", "icon": "📊"},
            "operations_output": {"title": "9. Operations Checklist", "icon": "⚙️"},
        }

        for key, meta in section_map.items():
            if key in context and context[key]:
                report["sections"].append({
                    "title": meta["title"],
                    "icon": meta["icon"],
                    "content": context[key],
                })

        return report

    def generate_pdf(self, report: Dict[str, Any], output_path: str) -> str:
        """Generate a PDF from the compiled report using ReportLab."""
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.lib.colors import HexColor
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

            doc = SimpleDocTemplate(output_path, pagesize=A4,
                                    topMargin=0.75*inch, bottomMargin=0.75*inch)

            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'CustomTitle', parent=styles['Title'],
                fontSize=24, spaceAfter=30,
                textColor=HexColor('#1a1a2e')
            )
            heading_style = ParagraphStyle(
                'CustomHeading', parent=styles['Heading1'],
                fontSize=16, spaceAfter=12, spaceBefore=20,
                textColor=HexColor('#16213e')
            )
            body_style = ParagraphStyle(
                'CustomBody', parent=styles['Normal'],
                fontSize=11, spaceAfter=8, leading=16,
            )

            elements = []

            # Title
            elements.append(Paragraph(report.get("title", "Business Plan"), title_style))
            elements.append(Spacer(1, 20))

            # Sections
            for section in report.get("sections", []):
                elements.append(Paragraph(
                    f"{section['icon']} {section['title']}", heading_style
                ))

                def _esc(text):
                    """Escape ReportLab paragraph markup."""
                    return (str(text).replace("&", "&amp;")
                            .replace("<", "&lt;").replace(">", "&gt;"))

                def _render(value, indent=0, label=None):
                    """Recursively render any nested structure with real depth."""
                    pad = "&nbsp;" * (indent * 4)
                    nice = label.replace("_", " ").title() if label else None
                    if isinstance(value, dict):
                        if nice:
                            elements.append(Paragraph(f"{pad}<b>{_esc(nice)}</b>", body_style))
                        for k, v in value.items():
                            _render(v, indent + (1 if nice else 0), str(k))
                    elif isinstance(value, list):
                        if nice:
                            elements.append(Paragraph(f"{pad}<b>{_esc(nice)}:</b>", body_style))
                        for item in value:
                            if isinstance(item, (dict, list)):
                                _render(item, indent + 1)
                            else:
                                elements.append(Paragraph(f"{pad}&nbsp;&nbsp;• {_esc(item)}", body_style))
                    else:
                        if nice:
                            elements.append(Paragraph(f"{pad}<b>{_esc(nice)}:</b> {_esc(value)}", body_style))
                        else:
                            elements.append(Paragraph(f"{pad}• {_esc(value)}", body_style))

                content = section.get("content", {})
                if isinstance(content, dict):
                    for key, value in content.items():
                        _render(value, 0, str(key))
                elif content:
                    _render(content, 0)

                elements.append(Spacer(1, 15))

            doc.build(elements)
            logger.info(f"PDF generated: {output_path}")
            return output_path

        except ImportError:
            logger.warning("ReportLab not installed, saving as JSON instead")
            json_path = output_path.replace(".pdf", ".json")
            with open(json_path, "w") as f:
                json.dump(report, f, indent=2)
            return json_path
