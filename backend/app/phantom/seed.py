"""Seed snapshot — so a fresh clone shows the real Phantom Hunter data in seconds.

The working database is not in git: it holds user accounts and full article text
copied from news sites. The snapshot keeps only what is ours to publish:

* articles  — metadata only (title, source, URL, date, feed). **No article body.**
* mentions  — the LLM extraction + the verifier's verdict on every field
              (the `context` sentences copied from the article are dropped)
* projects, evidence (short verified quotes), anomalies — exactly as scored

No users, no AgentForge runs, no secrets.

    python -m app.phantom.seed --export   # DB → seed/phantom_seed.json.gz (maintainers)
    python -m app.phantom.seed            # seed/phantom_seed.json.gz → DB (if Phantom tables are empty)
    python -m app.phantom.seed --force    # replace whatever Phantom data is there

The app also seeds itself on startup when the Phantom tables are empty
(set PHANTOM_AUTO_SEED=false to disable).
"""

from __future__ import annotations

import gzip
import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from sqlalchemy import Boolean, DateTime, Float, Integer

from app.database import SessionLocal
from app.phantom.models import PhAnomaly, PhArticle, PhEvidence, PhMention, PhProject

logger = logging.getLogger(__name__)

SEED_FILE = Path(__file__).resolve().parents[2] / "seed" / "phantom_seed.json.gz"
# load order respects foreign keys; delete order is the reverse
TABLES = [("articles", PhArticle), ("projects", PhProject), ("mentions", PhMention), ("evidence", PhEvidence), ("anomalies", PhAnomaly)]
DROP_ARTICLE = {"text", "content_hash"}       # never redistribute article bodies
DROP_MENTION_DATA = {"context"}                # sentences copied from the article


def _dump(row) -> Dict[str, Any]:
    out = {}
    for col in row.__table__.columns:
        v = getattr(row, col.name)
        if isinstance(v, uuid.UUID):
            v = str(v)
        elif isinstance(v, datetime):
            v = v.isoformat()
        out[col.name] = v
    return out


def _load(model, rec: Dict[str, Any]):
    kw = {}
    for col in model.__table__.columns:
        if col.name not in rec:
            continue
        v = rec[col.name]
        if v is not None:
            t = col.type
            if isinstance(t, DateTime):
                v = datetime.fromisoformat(v)
            elif isinstance(t, (Integer, Float, Boolean)):
                pass
            elif type(t).__name__ == "GUID":
                v = uuid.UUID(v)
        kw[col.name] = v
    return model(**kw)


def export(path: Path = SEED_FILE, db=None) -> Dict[str, int]:
    own = db is None
    db = db or SessionLocal()
    try:
        from app.phantom.geo import resolve_place
        from app.phantom.pipeline import _load_mentions

        # Final, verified view of each mention (LLM events re-verified + miner events), computed while
        # the article text is still available — a rebuild from the snapshot reuses it as-is.
        final = {m["id"]: m["data"] for m in _load_mentions(db)}
        snap: Dict[str, Any] = {"version": 1, "exported_at": datetime.utcnow().isoformat() + "Z"}
        for name, model in TABLES:
            rows = []
            for r in db.query(model).all():
                d = _dump(r)
                if model is PhArticle:
                    for k in DROP_ARTICLE:
                        d[k] = None
                if model is PhMention:
                    data = final.get(r.id, d["data"] or {})
                    # the resolver reads the article context to place a project; keep only its answer
                    place = resolve_place(data.get("city"), data.get("state"), data.get("project_name"),
                                          data.get("details_quote"), *(data.get("context") or []))
                    d["data"] = {**{k: v for k, v in data.items() if k not in DROP_MENTION_DATA}, "_place": place, "_frozen": True}
                rows.append(d)
            snap[name] = rows
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, separators=(",", ":"))
        return {name: len(snap[name]) for name, _ in TABLES}
    finally:
        if own:
            db.close()


def is_empty(db) -> bool:
    return db.query(PhProject).count() == 0


def load(path: Path = SEED_FILE, force: bool = False, db=None) -> Dict[str, int]:
    """Load the snapshot. Skips (returns {}) when Phantom data already exists, unless force."""
    if not path.exists():
        raise FileNotFoundError(path)
    own = db is None
    db = db or SessionLocal()
    try:
        if not is_empty(db) and not force:
            return {}
        for _, model in reversed(TABLES):
            db.query(model).delete()
        db.flush()
        with gzip.open(path, "rt", encoding="utf-8") as f:
            snap = json.load(f)
        counts = {}
        for name, model in TABLES:
            db.add_all(_load(model, rec) for rec in snap.get(name, []))
            db.flush()
            counts[name] = len(snap.get(name, []))
        db.commit()
        return counts
    except Exception:
        db.rollback()
        raise
    finally:
        if own:
            db.close()


def auto_seed() -> None:
    """Startup hook: fill empty Phantom tables from the snapshot. Never fails startup."""
    try:
        counts = load()
        if counts:
            logger.info(f"Phantom Hunter: seeded demo data {counts}")
    except FileNotFoundError:
        pass
    except Exception as e:  # pragma: no cover — seeding is a convenience, not a requirement
        logger.warning(f"Phantom Hunter: auto-seed skipped ({e!r})")


if __name__ == "__main__":
    from app.database import init_db

    init_db()
    if "--export" in sys.argv:
        print("exported", export(), "→", SEED_FILE)
    else:
        counts = load(force="--force" in sys.argv)
        print(f"seeded {counts}" if counts else "Phantom tables already have data — use --force to replace them")
