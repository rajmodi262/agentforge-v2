"""Phantom Hunter tables.

Article ──< Mention ──> Project ──< Evidence
                                 ──< Anomaly

* Article  — one fetched news item (raw text kept, so every claim can be re-checked).
* Mention  — one project as described by one article, as extracted by the LLM,
             with the verifier's verdict on every field.
* Project  — the resolved, de-duplicated project (many mentions → one project).
* Evidence — one verified event on the evidence ladder (e.g. "POWER: signed PPA").
* Anomaly  — a change worth flagging (capacity cut, date slip, opposition, stale).
"""

from sqlalchemy import Column, String, Text, Integer, Float, DateTime, ForeignKey, JSON, Boolean, Index
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.db_models import GUID, new_uuid, utcnow


class PhArticle(Base):
    __tablename__ = "ph_articles"
    __table_args__ = (Index("ix_ph_articles_hash", "content_hash"),)

    id = Column(GUID, primary_key=True, default=new_uuid)
    url = Column(String(1000), unique=True, nullable=False)
    title = Column(String(500), nullable=False)
    source = Column(String(200))            # publisher, e.g. "The Edge Malaysia"
    feed = Column(String(50))               # which scout found it: bing | google | gdelt
    query = Column(String(300))             # the search query that surfaced it
    published_at = Column(DateTime(timezone=True))
    fetched_at = Column(DateTime(timezone=True), default=utcnow)
    text = Column(Text)                     # full article text, or the feed summary if blocked
    text_kind = Column(String(20))          # "full" | "summary" (publisher blocked the fetch)
    content_hash = Column(String(64))
    relevant = Column(Boolean, default=None)
    extracted = Column(Boolean, default=False)

    mentions = relationship("PhMention", back_populates="article", cascade="all, delete-orphan")


class PhProject(Base):
    __tablename__ = "ph_projects"

    id = Column(GUID, primary_key=True, default=new_uuid)
    name = Column(String(300), nullable=False)
    developer = Column(String(200))
    city = Column(String(120))
    state = Column(String(120))
    country = Column(String(80))
    lat = Column(Float)
    lon = Column(Float)
    capacity_mw = Column(Float)             # canonical (see resolve.canonical_capacity)
    capacity_basis = Column(String(20))     # IT | facility | campus | unknown
    target_year = Column(Integer)
    power_partner = Column(String(200))
    power_source = Column(String(120))
    cooling = Column(String(120))
    ai_density = Column(Boolean, default=False)

    stage = Column(Integer, default=0)      # highest verified ladder layer (0–5)
    reality_score = Column(Float)           # 0–1 probability the project gets built
    score_breakdown = Column(JSON)          # every term that moved the score
    weakest_assumption = Column(Text)
    call_segments = Column(JSON)            # who-to-call ranking per buyer segment
    debate = Column(JSON)                   # Bull vs Bear transcript + verdict
    n_sources = Column(Integer, default=0)
    first_seen = Column(DateTime(timezone=True))
    last_seen = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    mentions = relationship("PhMention", back_populates="project")
    evidence = relationship("PhEvidence", back_populates="project", cascade="all, delete-orphan")
    anomalies = relationship("PhAnomaly", back_populates="project", cascade="all, delete-orphan")


class PhMention(Base):
    __tablename__ = "ph_mentions"

    id = Column(GUID, primary_key=True, default=new_uuid)
    article_id = Column(GUID, ForeignKey("ph_articles.id"), nullable=False, index=True)
    project_id = Column(GUID, ForeignKey("ph_projects.id"), nullable=True, index=True)
    data = Column(JSON, nullable=False)     # the extracted mention (schema.ProjectMention)
    verification = Column(JSON)             # per-field verdicts from verify.py
    verified_ratio = Column(Float)          # share of claims that survived verification
    model = Column(String(80))
    created_at = Column(DateTime(timezone=True), default=utcnow)

    article = relationship("PhArticle", back_populates="mentions")
    project = relationship("PhProject", back_populates="mentions")


class PhEvidence(Base):
    __tablename__ = "ph_evidence"

    id = Column(GUID, primary_key=True, default=new_uuid)
    project_id = Column(GUID, ForeignKey("ph_projects.id"), nullable=False, index=True)
    article_id = Column(GUID, ForeignKey("ph_articles.id"), nullable=False)
    layer = Column(String(20), nullable=False)   # ANNOUNCED … LIVE, or a negative signal
    detail = Column(Text)
    quote = Column(Text)                          # the exact supporting sentence
    event_date = Column(DateTime(timezone=True))  # article date if the event has none
    verified = Column(Boolean, default=False)

    project = relationship("PhProject", back_populates="evidence")


class PhAnomaly(Base):
    __tablename__ = "ph_anomalies"

    id = Column(GUID, primary_key=True, default=new_uuid)
    project_id = Column(GUID, ForeignKey("ph_projects.id"), nullable=False, index=True)
    kind = Column(String(40), nullable=False)     # capacity_conflict | date_slip | negative_signal | stale
    severity = Column(String(10))                 # low | medium | high
    message = Column(Text, nullable=False)
    details = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    project = relationship("PhProject", back_populates="anomalies")


class PhRun(Base):
    """One hunt: which queries ran, what they found, what each agent did."""
    __tablename__ = "ph_runs"

    id = Column(GUID, primary_key=True, default=new_uuid)
    region = Column(String(80))
    status = Column(String(20), default="running")
    stats = Column(JSON)
    log = Column(JSON)
    started_at = Column(DateTime(timezone=True), default=utcnow)
    finished_at = Column(DateTime(timezone=True))
