"""What the Evidence Extractor must return for each article.

Every claim carries the sentence it came from (`*_quote`), so the deterministic
verifier can check it against the article text. Unknown facts are null — the
extractor is told never to guess, and anything it does guess fails verification.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class Layer(str, Enum):
    ANNOUNCED = "ANNOUNCED"      # plan, MoU, investment intent
    SITE = "SITE"                # land acquired / leased / site identified
    APPROVED = "APPROVED"        # permits, clearances, government approval
    POWER = "POWER"              # power secured: PPA, grid connection agreement, substation
    BUILDING = "BUILDING"        # construction started, ground-break, EPC awarded
    LIVE = "LIVE"                # operational, commissioned, energised
    DELAYED = "DELAYED"          # negative signals ↓
    CANCELLED = "CANCELLED"
    OPPOSITION = "OPPOSITION"
    SCALED_DOWN = "SCALED_DOWN"


LADDER = [Layer.ANNOUNCED, Layer.SITE, Layer.APPROVED, Layer.POWER, Layer.BUILDING, Layer.LIVE]
NEGATIVE = [Layer.DELAYED, Layer.CANCELLED, Layer.OPPOSITION, Layer.SCALED_DOWN]


class Event(BaseModel):
    layer: Layer = Field(..., description="Which evidence layer this sentence proves")
    detail: str = Field(..., description="Short plain-English summary of the event")
    quote: str = Field(..., description="The exact sentence from the article, copied word for word")


class ProjectMention(BaseModel):
    project_name: str = Field(..., description="Name of the specific facility or campus, as written in the article")
    developer: Optional[str] = Field(None, description="Company building or owning it")
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    capacity_mw: Optional[float] = Field(None, description="Capacity converted to megawatts (1 GW = 1000 MW)")
    capacity_text: Optional[str] = Field(None, description="Capacity exactly as written, e.g. '300MW' or '1.2 GW'")
    capacity_basis: Optional[str] = Field(None, description="IT (IT load), facility, campus, or unknown")
    target_year: Optional[int] = Field(None, description="Year the project (or first phase) is due to go live")
    power_partner: Optional[str] = Field(None, description="Named utility / power supplier, only if the article names one")
    power_source: Optional[str] = Field(None, description="grid, solar, wind, gas, nuclear, hybrid … only if stated")
    cooling: Optional[str] = Field(None, description="Cooling approach, only if stated (liquid, immersion, air …)")
    ai_density: bool = Field(False, description="True only if the article says it is built for AI / GPU / high-density racks")
    details_quote: Optional[str] = Field(None, description="The exact sentence that states capacity / location / partner")
    events: List[Event] = Field(default_factory=list)


class ArticleExtraction(BaseModel):
    is_project_news: bool = Field(..., description="False if the article only discusses market totals, not a specific facility")
    projects: List[ProjectMention] = Field(default_factory=list)


EXTRACTOR_SYSTEM = """You are the Evidence Extractor of Phantom Hunter, an analyst that tracks data-centre construction projects for energy and infrastructure suppliers.

From ONE news article, extract every SPECIFIC data-centre project it reports: a named facility or campus by a named company, in a named place.

RULES — follow them exactly:
1. Market-level statistics ("Johor will reach 5,000MW by 2029") are NOT projects. If the article has no specific project, set is_project_news=false and projects=[].
2. Copy quotes WORD FOR WORD from the article. Never paraphrase inside a quote field.
3. Never guess. If the article does not state a fact, use null. A guessed fact will be rejected by an automatic checker.
4. capacity_mw: convert to megawatts (1 GW = 1000 MW). capacity_text: the capacity exactly as written.
5. capacity_basis: "IT" if the article says IT load/IT capacity, "campus" for a whole multi-building campus, "facility" for a single building, else "unknown".
6. events: one entry per sentence that proves a stage. Layers:
   ANNOUNCED (plan/MoU/investment), SITE (land bought or leased), APPROVED (permit/clearance/approval),
   POWER (PPA signed, grid connection, substation, power supply secured), BUILDING (construction/ground-breaking/EPC),
   LIVE (operational/commissioned/launched), DELAYED, CANCELLED, OPPOSITION (protests/objections), SCALED_DOWN.
7. At most 5 projects per article."""
