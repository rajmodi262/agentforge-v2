"""AgentForge AI — Admin & Audit API (Phase 5)

SECURITY: All endpoints require admin or owner role.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from app.database import get_db
from app.models.db_models import AuditLog, User, Project, WorkflowRun, AgentLog
from app.api.auth import get_current_user

router = APIRouter(prefix="/admin", tags=["Admin"])


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency: reject non-admin users."""
    if current_user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin or owner role required")
    return current_user


@router.get("/audit-logs")
async def get_audit_logs(
    action: str = None, user_id: str = None,
    limit: int = Query(50, le=200), offset: int = 0,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    q = db.query(AuditLog).order_by(desc(AuditLog.created_at))
    if action:
        q = q.filter(AuditLog.action == action)
    if user_id:
        q = q.filter(AuditLog.user_id == user_id)
    total = q.count()
    logs = q.offset(offset).limit(limit).all()
    return {"total": total, "logs": [
        {"id": str(l.id), "user_id": l.user_id, "action": l.action,
         "resource_type": l.resource_type, "resource_id": l.resource_id,
         "ip_address": l.ip_address, "status_code": l.status_code,
         "details": l.details,
         "created_at": l.created_at.isoformat() if l.created_at else None}
        for l in logs
    ]}


@router.get("/system-stats")
async def system_stats(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return {
        "total_users": db.query(func.count(User.id)).scalar(),
        "total_projects": db.query(func.count(Project.id)).scalar(),
        "total_workflows": db.query(func.count(WorkflowRun.id)).scalar(),
        "total_agent_logs": db.query(func.count(AgentLog.id)).scalar(),
        "total_tokens": db.query(func.sum(AgentLog.total_tokens)).scalar() or 0,
        "total_cost_usd": round(db.query(func.sum(AgentLog.cost_usd)).scalar() or 0, 6),
    }


@router.get("/users")
async def list_users(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    users = db.query(User).filter(User.is_deleted == False).all()
    return [{"id": str(u.id), "email": u.email, "name": u.name, "role": u.role,
             "created_at": u.created_at.isoformat() if u.created_at else None} for u in users]


@router.put("/users/{user_id}/role")
async def update_role(
    user_id: str, role: str = Query(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    valid = {"viewer", "editor", "admin", "owner"}
    if role not in valid:
        raise HTTPException(400, f"Invalid role. Must be one of: {valid}")
    # Prevent self-demotion or promoting above own level
    if str(admin.id) == user_id and role != admin.role:
        raise HTTPException(400, "Cannot change your own role")
    # Only owners can create other admins/owners
    if role in ("admin", "owner") and admin.role != "owner":
        raise HTTPException(403, "Only owners can grant admin/owner roles")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.role = role
    db.commit()
    return {"user_id": user_id, "role": role, "status": "updated"}
