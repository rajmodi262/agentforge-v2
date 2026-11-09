"""Seed snapshot: a fresh clone gets the real data, without article bodies or users."""

import gzip
import json
from datetime import datetime, timezone

from app.phantom.models import PhArticle, PhEvidence, PhMention, PhProject
from app.phantom.seed import SEED_FILE, export, load


def _fill(db):
    d = datetime(2026, 9, 1, tzinfo=timezone.utc)
    a = PhArticle(url="https://example.com/x", title="AirTrunk JHB2 signs PPA", source="DCD", feed="bing", published_at=d,
                  text="FULL ARTICLE BODY that must never be redistributed. AirTrunk signed a PPA with TNB for JHB2.",
                  text_kind="full", relevant=True, extracted=True)
    db.add(a)
    db.flush()
    p = PhProject(name="AirTrunk JHB2", developer="AirTrunk", country="Malaysia", state="Johor", capacity_mw=150,
                  reality_score=0.8, stage=3, n_sources=1, first_seen=d, last_seen=d, power_partner="TNB")
    db.add(p)
    db.flush()
    db.add(PhMention(article_id=a.id, project_id=p.id, verified_ratio=1.0, verification={"capacity_mw": {"ok": True}},
                     data={"project_name": "JHB2", "developer": "AirTrunk", "country": "Malaysia", "city": "Kulai",
                           "context": ["sentence copied from the article"],
                           "events": [{"layer": "POWER", "quote": "AirTrunk signed a PPA with TNB for JHB2."}]}))
    db.add(PhEvidence(project_id=p.id, article_id=a.id, layer="POWER", quote="AirTrunk signed a PPA with TNB for JHB2.", event_date=d, verified=True))
    db.commit()


def test_export_drops_article_bodies_and_context(db_session, tmp_path):
    _fill(db_session)
    path = tmp_path / "seed.json.gz"
    counts = export(path, db=db_session)
    assert counts == {"articles": 1, "projects": 1, "mentions": 1, "evidence": 1, "anomalies": 0}
    snap = json.load(gzip.open(path, "rt", encoding="utf-8"))
    blob = json.dumps(snap)
    assert "FULL ARTICLE BODY" not in blob and "sentence copied from the article" not in blob
    m = snap["mentions"][0]["data"]
    assert m["_frozen"] is True and "_place" in m and m["events"]          # verified events kept for rebuilds
    assert set(snap) == {"version", "exported_at", "articles", "projects", "mentions", "evidence", "anomalies"}  # no users


def test_load_round_trip_and_skip_when_data_exists(db_session, tmp_path):
    _fill(db_session)
    path = tmp_path / "seed.json.gz"
    export(path, db=db_session)
    assert load(path, db=db_session) == {}                                  # existing data is never overwritten silently
    counts = load(path, force=True, db=db_session)
    assert counts["projects"] == 1 and counts["articles"] == 1
    p = db_session.query(PhProject).one()
    assert p.name == "AirTrunk JHB2" and p.capacity_mw == 150 and p.first_seen.year == 2026
    assert db_session.query(PhArticle).one().text is None


def test_committed_snapshot_is_clean():
    """The snapshot shipped in the repo carries no article bodies and no user data."""
    snap = json.load(gzip.open(SEED_FILE, "rt", encoding="utf-8"))
    assert len(snap["projects"]) >= 100
    assert all(a["text"] is None for a in snap["articles"])
    assert not any("context" in m["data"] for m in snap["mentions"])
    assert "hashed_password" not in json.dumps(snap)
