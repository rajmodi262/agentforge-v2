"""AgentForge AI — API Router (aggregates all route modules)"""

from fastapi import APIRouter
from app.api.auth import router as auth_router
from app.api.projects import router as projects_router
from app.api.results import router as results_router
from app.api.workflow import router as workflow_router
from app.api.websocket import router as websocket_router
from app.api.graph import router as graph_router
from app.api.observability import router as observability_router
from app.api.knowledge import router as knowledge_router
from app.api.prompts import router as prompts_router
from app.api.admin import router as admin_router
from app.api.n8n import router as n8n_router
from app.api.mcp import router as mcp_router
from app.api.share import router as share_router
from app.api.phantom import router as phantom_router

api_router = APIRouter()

api_router.include_router(share_router, tags=["Sharing"])

api_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_router.include_router(projects_router, prefix="/projects", tags=["Projects"])
api_router.include_router(results_router, prefix="/projects", tags=["Results"])
api_router.include_router(workflow_router, prefix="/workflow", tags=["Workflow"])
api_router.include_router(websocket_router, tags=["WebSocket"])
api_router.include_router(graph_router, tags=["Workflow Graph"])
api_router.include_router(observability_router, tags=["Observability"])
api_router.include_router(knowledge_router, tags=["Knowledge Base"])
api_router.include_router(prompts_router, tags=["Prompt IDE"])
api_router.include_router(admin_router, tags=["Admin"])
api_router.include_router(n8n_router, tags=["n8n Integration"])
api_router.include_router(mcp_router, tags=["MCP Protocol"])
api_router.include_router(phantom_router)


