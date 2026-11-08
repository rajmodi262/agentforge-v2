"""AgentForge AI — Observability API (Phase 1)

Full LLMOps observability matching/exceeding Dify:
- Paginated agent logs with filtering
- Aggregate metrics (tokens, cost, latency, error rate)
- Time-series data for charts
- User feedback on agent outputs
- Cost breakdown per agent/provider
"""

import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import Optional

from app.database import get_db
from app.api.auth import get_current_user
from app.api.admin import require_admin
from app.models.db_models import AgentLog, WorkflowRun, AgentTask, Project, User

router = APIRouter(prefix="/observability", tags=["Observability"], dependencies=[Depends(get_current_user)])


@router.get("/logs")
async def get_logs(
    workflow_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Paginated agent logs with filters. Non-admins only see logs of their own runs
    (log previews contain the user's business idea)."""
    query = db.query(AgentLog).order_by(desc(AgentLog.created_at))
    if user.role not in ("admin", "owner"):
        own = db.query(WorkflowRun.id).join(Project, WorkflowRun.project_id == Project.id).filter(Project.user_id == user.id)
        query = query.filter(AgentLog.workflow_id.in_(own))

    if workflow_id:
        query = query.filter(AgentLog.workflow_id == workflow_id)
    if agent_name:
        query = query.filter(AgentLog.agent_name == agent_name)
    if status:
        query = query.filter(AgentLog.status == status)

    total = query.count()
    logs = query.offset(offset).limit(limit).all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "logs": [
            {
                "id": str(log.id),
                "workflow_id": str(log.workflow_id),
                "agent_name": log.agent_name,
                "prompt_tokens": log.prompt_tokens,
                "completion_tokens": log.completion_tokens,
                "total_tokens": log.total_tokens,
                "latency_ms": log.latency_ms,
                "model_provider": log.model_provider,
                "model_name": log.model_name,
                "cost_usd": log.cost_usd,
                "status": log.status,
                "error_message": log.error_message,
                "input_preview": log.input_preview,
                "output_preview": log.output_preview,
                "feedback_score": log.feedback_score,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    }


@router.get("/metrics")
async def get_metrics(
    days: int = Query(30, le=365),
    db: Session = Depends(get_db),
):
    """Aggregate observability metrics."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    logs = db.query(AgentLog).filter(AgentLog.created_at >= cutoff)

    total_logs = logs.count()
    if total_logs == 0:
        return {
            "period_days": days,
            "total_calls": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "avg_latency_ms": 0,
            "error_rate": 0.0,
            "success_rate": 1.0,
            "fallback_rate": 0.0,
        }

    metrics = db.query(
        func.count(AgentLog.id).label("total_calls"),
        func.sum(AgentLog.total_tokens).label("total_tokens"),
        func.sum(AgentLog.cost_usd).label("total_cost"),
        func.avg(AgentLog.latency_ms).label("avg_latency"),
    ).filter(AgentLog.created_at >= cutoff).first()

    error_count = logs.filter(AgentLog.status == "error").count()
    fallback_count = logs.filter(AgentLog.status == "fallback").count()

    return {
        "period_days": days,
        "total_calls": metrics.total_calls or 0,
        "total_tokens": metrics.total_tokens or 0,
        "total_cost_usd": round(metrics.total_cost or 0.0, 6),
        "avg_latency_ms": round(metrics.avg_latency or 0, 1),
        "error_rate": round(error_count / total_logs, 4) if total_logs > 0 else 0,
        "success_rate": round((total_logs - error_count) / total_logs, 4) if total_logs > 0 else 1,
        "fallback_rate": round(fallback_count / total_logs, 4) if total_logs > 0 else 0,
    }


@router.get("/metrics/by-agent")
async def get_metrics_by_agent(
    db: Session = Depends(get_db),
):
    """Per-agent performance breakdown."""
    results = db.query(
        AgentLog.agent_name,
        func.count(AgentLog.id).label("total_calls"),
        func.sum(AgentLog.total_tokens).label("total_tokens"),
        func.sum(AgentLog.cost_usd).label("total_cost"),
        func.avg(AgentLog.latency_ms).label("avg_latency"),
    ).group_by(AgentLog.agent_name).all()

    return [
        {
            "agent_name": r.agent_name,
            "total_calls": r.total_calls,
            "total_tokens": r.total_tokens or 0,
            "total_cost_usd": round(r.total_cost or 0, 6),
            "avg_latency_ms": round(r.avg_latency or 0, 1),
        }
        for r in results
    ]


@router.get("/metrics/by-provider")
async def get_metrics_by_provider(
    db: Session = Depends(get_db),
):
    """Per-provider cost and usage breakdown."""
    results = db.query(
        AgentLog.model_provider,
        func.count(AgentLog.id).label("total_calls"),
        func.sum(AgentLog.total_tokens).label("total_tokens"),
        func.sum(AgentLog.cost_usd).label("total_cost"),
    ).group_by(AgentLog.model_provider).all()

    return [
        {
            "provider": r.model_provider,
            "total_calls": r.total_calls,
            "total_tokens": r.total_tokens or 0,
            "total_cost_usd": round(r.total_cost or 0, 6),
        }
        for r in results
    ]


@router.post("/feedback/{log_id}")
async def submit_feedback(
    log_id: str,
    score: int = Query(..., ge=-1, le=1),
    db: Session = Depends(get_db),
):
    """Submit user feedback (thumbs up/down) on an agent output."""
    log = db.query(AgentLog).filter(AgentLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Log not found")

    log.feedback_score = score
    db.commit()
    return {"status": "ok", "log_id": log_id, "feedback_score": score}
