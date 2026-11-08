"""AgentForge AI — MCP API Endpoints

REST endpoints that expose the MCP protocol over HTTP.
Any MCP-compatible client can interact via these endpoints.
"""

from fastapi import APIRouter, Depends, Body
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.mcp_server import get_mcp_server
from app.api.auth import get_current_user
from app.api.admin import require_admin

router = APIRouter(prefix="/mcp", tags=["MCP"], dependencies=[Depends(get_current_user)])


@router.get("/initialize")
async def mcp_initialize():
    """MCP initialize — returns server info and capabilities."""
    mcp = get_mcp_server()
    return mcp.handle_initialize()


@router.get("/tools")
async def mcp_list_tools():
    """MCP tools/list — returns all available tools."""
    mcp = get_mcp_server()
    return mcp.handle_list_tools()


@router.get("/resources")
async def mcp_list_resources():
    """MCP resources/list — returns all available resources."""
    mcp = get_mcp_server()
    return mcp.handle_list_resources()


@router.get("/prompts")
async def mcp_list_prompts():
    """MCP prompts/list — returns all available prompt templates."""
    mcp = get_mcp_server()
    return mcp.handle_list_prompts()


@router.post("/tools/call")
async def mcp_call_tool(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),  # tools read across all projects
):
    """
    MCP tools/call — execute a tool.
    
    Body: { "name": "agentforge_list_agents", "arguments": {} }
    """
    name = payload.get("name", "")
    arguments = payload.get("arguments", {})
    mcp = get_mcp_server()
    result = await mcp.handle_call_tool(name, arguments, db)
    return result


@router.get("/health")
async def mcp_health():
    """MCP server health check."""
    mcp = get_mcp_server()
    return {
        "status": "healthy",
        "server": mcp.server_info,
        "tools_count": len(mcp._tools),
        "resources_count": len(mcp._resources),
        "prompts_count": len(mcp._prompts),
    }
