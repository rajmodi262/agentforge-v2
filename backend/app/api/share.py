"""AgentForge AI — Shareable Links API

Only a project's owner can create its share link; anyone holding the
unguessable token can then view the summary and download the PDF.
"""

import os
import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.orchestrator import REPORTS_DIR
from app.api.auth import get_current_user
from app.database import get_db
from app.models.db_models import Project, ProjectReport, User

router = APIRouter()


def generate_share_token() -> str:
    """A secure, random 32-character hex string."""
    return secrets.token_hex(16)


def _latest_report(db: Session, project_id) -> ProjectReport | None:
    stmt = select(ProjectReport).where(ProjectReport.project_id == project_id).order_by(ProjectReport.generated_at.desc())
    return db.execute(stmt).scalars().first()


def _project_by_token(db: Session, share_token: str) -> Project:
    project = db.execute(select(Project).where(Project.share_token == share_token, Project.is_deleted == False)).scalar_one_or_none()  # noqa: E712
    if not project:
        raise HTTPException(status_code=404, detail="Shared link not found or expired")
    return project


@router.post("/projects/{project_id}/share", response_model=dict)
def generate_share_link(project_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Create (or return) the share link for a project you own."""
    project = db.execute(select(Project).where(Project.id == project_id, Project.user_id == user.id,
                                               Project.is_deleted == False)).scalar_one_or_none()  # noqa: E712
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not project.share_token:
        project.share_token = generate_share_token()
        db.commit()
        db.refresh(project)
    return {"share_token": project.share_token, "share_url": f"/shared/{project.share_token}"}


@router.get("/shared/{share_token}")
def get_shared_project(share_token: str, db: Session = Depends(get_db)):
    """Basic project details for a shared link (no login needed — the token is the key)."""
    project = _project_by_token(db, share_token)
    report = _latest_report(db, project.id)
    return {
        "title": project.title,
        "business_idea": project.business_idea,
        "target_market": project.target_market,
        "budget_range": project.budget_range,
        "status": project.status,
        "has_report": report is not None,
        "report_id": str(report.id) if report else None,
    }


@router.get("/shared/{share_token}/report/download")
def download_shared_report(share_token: str, db: Session = Depends(get_db)):
    """Download the PDF report using a share token."""
    project = _project_by_token(db, share_token)
    report = _latest_report(db, project.id)
    if not report or not report.file_path:
        raise HTTPException(status_code=404, detail="Report not available")
    # file_path is stored relative to REPORTS_DIR; basename() blocks path traversal
    report_path = os.path.join(REPORTS_DIR, os.path.basename(report.file_path))
    if not os.path.exists(report_path):
        raise HTTPException(status_code=404, detail="Report file not found on disk")
    safe_title = "".join(ch if ch.isalnum() else "_" for ch in project.title)[:40]
    return FileResponse(path=report_path, filename=f"AgentForge_Blueprint_{safe_title}.pdf", media_type="application/pdf")
