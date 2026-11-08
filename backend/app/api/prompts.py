"""AgentForge AI — Prompt Management API (Phase 4)"""

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional
from uuid import UUID
from app.database import get_db
from app.models.db_models import PromptVersion
from app.agents.ceo_agent import CEOAgent
from app.agents.research_agent import ResearchAgent
from app.agents.marketing_agent import MarketingAgent
from app.agents.developer_agent import DeveloperAgent
from app.agents.finance_agent import FinanceAgent
from app.agents.analytics_agent import AnalyticsAgent
from app.agents.operations_agent import OperationsAgent
from app.api.auth import get_current_user
from app.api.admin import require_admin

# Reading prompts needs a login; changing them needs admin — an active prompt changes
# every user's agents, so it is an admin action.
router = APIRouter(prefix="/prompts", tags=["Prompt IDE"], dependencies=[Depends(get_current_user)])

AGENT_REGISTRY = {
    "ceo": CEOAgent, "research": ResearchAgent, "marketing": MarketingAgent,
    "developer": DeveloperAgent, "finance": FinanceAgent,
    "analytics": AnalyticsAgent, "operations": OperationsAgent,
}


@router.get("/agents")
async def list_agents():
    return [{"key": k, "name": c.name, "prompt_preview": c.system_prompt[:200],
             "context_keys": c.required_context_keys, "schema": c.output_schema}
            for k, c in AGENT_REGISTRY.items()]


@router.get("/{agent_name}/versions")
async def list_versions(agent_name: str, db: Session = Depends(get_db)):
    if agent_name not in AGENT_REGISTRY:
        raise HTTPException(404, f"Agent '{agent_name}' not found")
    versions = db.query(PromptVersion).filter(
        PromptVersion.agent_name == agent_name).order_by(desc(PromptVersion.version)).all()
    cls = AGENT_REGISTRY[agent_name]
    result = [{"id": "current", "version": 0, "system_prompt": cls.system_prompt,
               "is_active": not any(v.is_active for v in versions), "notes": "Default"}]
    for v in versions:
        result.append({"id": str(v.id), "version": v.version,
                       "system_prompt": v.system_prompt, "is_active": v.is_active,
                       "notes": v.notes, "score": v.performance_score,
                       "created_at": v.created_at.isoformat() if v.created_at else None})
    return result


@router.post("/{agent_name}/versions")
async def create_version(agent_name: str, system_prompt: str = Body(...),
                         notes: Optional[str] = Body(None), db: Session = Depends(get_db), admin=Depends(require_admin)):
    if agent_name not in AGENT_REGISTRY:
        raise HTTPException(404, f"Agent '{agent_name}' not found")
    mx = db.query(PromptVersion).filter(PromptVersion.agent_name == agent_name
                                         ).order_by(desc(PromptVersion.version)).first()
    v = PromptVersion(agent_name=agent_name, version=(mx.version + 1) if mx else 1,
                      system_prompt=system_prompt, notes=notes,
                      output_schema=AGENT_REGISTRY[agent_name].output_schema)
    db.add(v)
    db.commit()
    return {"id": str(v.id), "version": v.version, "status": "created"}


@router.put("/{agent_name}/versions/{vid}/activate")
async def activate_version(agent_name: str, vid: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    if agent_name not in AGENT_REGISTRY:
        raise HTTPException(404, f"Agent '{agent_name}' not found")
    db.query(PromptVersion).filter(PromptVersion.agent_name == agent_name
                                    ).update({"is_active": False})
    if vid != "current":
        try:
            UUID(vid)
        except ValueError:
            raise HTTPException(400, "Invalid version id")
        ver = db.query(PromptVersion).filter(PromptVersion.id == vid, PromptVersion.agent_name == agent_name).first()
        if not ver:
            raise HTTPException(404, "Version not found")
        ver.is_active = True
    db.commit()
    return {"active_version": vid, "status": "activated"}
