"""AgentForge AI — n8n Integration API

Manage n8n webhook connections and view integration status.
Gives AgentForge access to 400+ external service integrations.
"""

from fastapi import APIRouter, HTTPException, Body, Depends
from app.api.admin import require_admin
from app.services.n8n_service import get_n8n_service

# Admin only: a registered webhook receives workflow data, so registering one is privileged.
router = APIRouter(prefix="/integrations/n8n", tags=["n8n Integration"], dependencies=[Depends(require_admin)])


@router.get("/status")
async def n8n_status():
    """Get n8n integration status and available events."""
    svc = get_n8n_service()
    return svc.get_status()


@router.post("/webhooks")
async def register_webhook(
    event_type: str = Body(...),
    webhook_url: str = Body(...),
):
    """Register an n8n webhook URL for an event type.
    
    Event types:
    - workflow_completed: Fires when all agents finish
    - agent_completed: Fires after each agent
    - report_generated: Fires when PDF is ready
    - error_occurred: Fires on any workflow error
    
    The webhook_url should be your n8n Webhook node's production URL.
    """
    valid_events = {"workflow_completed", "agent_completed", "report_generated", "error_occurred"}
    from urllib.parse import urlparse
    import ipaddress, socket
    u = urlparse(webhook_url)
    if u.scheme != "https" or not u.hostname:
        raise HTTPException(400, "Webhook URL must be https")
    try:  # refuse private / loopback / link-local targets (SSRF)
        ip = ipaddress.ip_address(socket.gethostbyname(u.hostname))
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise HTTPException(400, "Webhook URL must point to a public host")
    except socket.gaierror:
        raise HTTPException(400, "Webhook host does not resolve")
    if event_type not in valid_events:
        raise HTTPException(400, f"Invalid event. Must be one of: {valid_events}")

    svc = get_n8n_service()
    svc.register_webhook(event_type, webhook_url)
    return {"status": "registered", "event_type": event_type, "webhook_url": webhook_url}


@router.get("/webhooks")
async def list_webhooks():
    """List all registered n8n webhooks."""
    svc = get_n8n_service()
    return {"webhooks": svc._webhooks}


@router.delete("/webhooks/{event_type}")
async def remove_webhook(event_type: str):
    """Remove a registered webhook."""
    svc = get_n8n_service()
    if event_type in svc._webhooks:
        del svc._webhooks[event_type]
        return {"status": "removed", "event_type": event_type}
    raise HTTPException(404, f"No webhook registered for '{event_type}'")


@router.post("/test/{event_type}")
async def test_webhook(event_type: str):
    """Send a test event to the registered webhook."""
    svc = get_n8n_service()
    result = await svc.fire_event(event_type, {
        "test": True,
        "message": f"Test event from AgentForge AI for '{event_type}'",
    })
    if result is None:
        raise HTTPException(404, f"No webhook registered for '{event_type}' or delivery failed")
    return {"status": "sent", "response": result}
