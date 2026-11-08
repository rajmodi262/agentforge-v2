"""AgentForge AI — Projects API

Production-grade:
- Soft-delete aware queries via active_query()
- UUID-based demo user isolation
- Relative report paths resolved at download time
"""

import asyncio
import os
import uuid
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from sqlalchemy.orm import Session

from app.database import get_db, active_query, soft_delete
from app.models.db_models import User, Project, WorkflowRun, ProjectReport
from app.models.request_schemas import CreateProjectRequest
from app.models.response_schemas import ProjectResponse, ProjectListResponse
from app.api.auth import get_current_user, get_optional_user
from app.agents.orchestrator import run_workflow, REPORTS_DIR

router = APIRouter()


# --- Demo user helper (for unauthenticated landing page demo) ---
def _get_or_create_demo_user(db: Session, request: Request = None) -> User:
    """Get or create a shared demo user for unauthenticated demo access.
    
    Using a shared demo user ensures that projects created anonymously 
    can immediately be started by subsequent requests from the same anonymous session.
    """
    demo_email = "demo@agentforge.ai"
    demo_user = db.query(User).filter(User.email == demo_email).first()
    
    if not demo_user:
        demo_user = User(
            email=demo_email,
            password_hash="$DEMO_USER_NO_LOGIN$",
            name="Shared Demo User",
        )
        db.add(demo_user)
        db.commit()
        db.refresh(demo_user)
        
    return demo_user



@router.post("/", response_model=ProjectResponse)
def create_project(
    request: CreateProjectRequest,
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Create a new project with a startup idea.
    
    Works for both authenticated users and anonymous demo users.
    Anonymous projects are linked to a shared demo user.
    """
    # If no auth token, use the demo user
    if current_user is None:
        current_user = _get_or_create_demo_user(db)

    project = Project(
        user_id=current_user.id,
        title=request.title,
        business_idea=request.business_idea,
        target_market=request.target_market,
        budget_range=request.budget_range,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/", response_model=ProjectListResponse)
def list_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all active projects for the current user. Requires authentication."""
    projects = active_query(db, Project).filter(
        Project.user_id == current_user.id
    ).order_by(Project.created_at.desc()).all()
    return ProjectListResponse(projects=projects, total=len(projects))


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a specific project. Requires authentication."""
    project = active_query(db, Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft-delete a project. Data is retained for recovery."""
    project = active_query(db, Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    soft_delete(db, project)
    db.commit()
    return None


@router.post("/{project_id}/start")
async def start_project_workflow(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Start the 7-agent workflow for a project.
    
    Works for both authenticated users and anonymous demo users.
    """
    # If no auth, use demo user
    if current_user is None:
        current_user = _get_or_create_demo_user(db)

    project = active_query(db, Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.status == "running":
        raise HTTPException(status_code=400, detail="Workflow already running")

    # Create workflow run
    workflow = WorkflowRun(project_id=project.id)
    db.add(workflow)
    project.status = "running"
    db.commit()
    db.refresh(workflow)

    # Build a session factory from the CURRENT session's engine
    # This ensures background tasks use the same DB as the request
    # (critical for tests where get_db is overridden to use in-memory SQLite)
    from sqlalchemy.orm import sessionmaker as _sessionmaker
    _factory = _sessionmaker(autocommit=False, autoflush=False, bind=db.get_bind())

    # Run workflow in background
    background_tasks.add_task(
        run_workflow,
        workflow_id=str(workflow.id),
        project_id=str(project.id),
        business_idea=project.business_idea,
        target_market=project.target_market,
        budget_range=project.budget_range,
        session_factory=_factory,
    )

    # Tell the client the effective AI mode immediately so it can badge demo runs
    from app.services.claude_service import get_claude_service
    mode = get_claude_service().mode_info()

    return {
        "message": "Workflow started",
        "workflow_id": str(workflow.id),
        "websocket_url": f"/api/v1/ws/{workflow.id}",
        "mode": mode["mode"],
        "provider": mode["provider"],
    }


@router.get("/{project_id}/report")
def download_report(
    project_id: UUID,
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Download the generated report for a project.
    
    Resolves the relative file_path stored in DB against REPORTS_DIR
    to find the actual file on disk.
    """
    from fastapi.responses import FileResponse

    # If no auth, use demo user
    if current_user is None:
        current_user = _get_or_create_demo_user(db)

    project = active_query(db, Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    report = db.query(ProjectReport).filter(
        ProjectReport.project_id == project_id,
    ).order_by(ProjectReport.generated_at.desc()).first()
    if not report or not report.file_path:
        raise HTTPException(status_code=404, detail="Report not generated yet")

    # Resolve relative path against REPORTS_DIR
    absolute_path = os.path.join(REPORTS_DIR, report.file_path)
    if not os.path.exists(absolute_path):
        # Fallback: check if file_path is already absolute (legacy data)
        if os.path.exists(report.file_path):
            absolute_path = report.file_path
        else:
            raise HTTPException(status_code=404, detail="Report file not found on disk")

    # Increment download count
    report.download_count = (report.download_count or 0) + 1
    db.commit()

    return FileResponse(
        path=absolute_path,
        filename=f"AgentForge_Blueprint_{project.title[:30]}.pdf",
        media_type="application/pdf",
    )
