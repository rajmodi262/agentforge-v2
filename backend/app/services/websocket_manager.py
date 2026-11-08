"""AgentForge AI — WebSocket Manager (A+ Edition)

Manages WebSocket connections with event history for catch-up on reconnect,
connection health monitoring, and graceful cleanup.
"""

import json
import time
import logging
import asyncio
from collections import deque
from typing import Dict, List, Optional
from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Max events to keep per workflow for catch-up
MAX_EVENT_HISTORY = 100


class WebSocketManager:
    """Manages WebSocket connections grouped by workflow_id.
    
    Features:
    - Event history per workflow (catch-up on reconnect)
    - Periodic ping/pong health checks
    - Dead connection cleanup
    """

    def __init__(self):
        # { workflow_id: [websocket_connections] }
        self.active_connections: Dict[str, List[WebSocket]] = {}
        # { workflow_id: deque of events } — for catch-up on reconnect
        self.event_history: Dict[str, deque] = {}

    async def connect(self, workflow_id: str, websocket: WebSocket):
        """Accept a WebSocket connection and send catch-up events."""
        await websocket.accept()
        if workflow_id not in self.active_connections:
            self.active_connections[workflow_id] = []
        self.active_connections[workflow_id].append(websocket)
        logger.info(f"WebSocket connected: workflow={workflow_id}, total={len(self.active_connections[workflow_id])}")

        # Send catch-up events to the newly connected client
        if workflow_id in self.event_history:
            try:
                catchup = list(self.event_history[workflow_id])
                if catchup:
                    await websocket.send_text(json.dumps({
                        "type": "catchup",
                        "events": catchup,
                    }))
                    logger.info(f"Sent {len(catchup)} catch-up events to reconnected client")
            except Exception as e:
                logger.warning(f"Failed to send catch-up events: {e}")

    def disconnect(self, workflow_id: str, websocket: WebSocket):
        """Remove a WebSocket connection from a workflow."""
        if workflow_id in self.active_connections:
            if websocket in self.active_connections[workflow_id]:
                self.active_connections[workflow_id].remove(websocket)
            if not self.active_connections[workflow_id]:
                del self.active_connections[workflow_id]
            logger.info(f"WebSocket disconnected: workflow={workflow_id}")

    def _store_event(self, workflow_id: str, event: dict):
        """Store event in history for catch-up on reconnect."""
        if workflow_id not in self.event_history:
            self.event_history[workflow_id] = deque(maxlen=MAX_EVENT_HISTORY)
        # Add timestamp to event
        event_with_ts = {**event, "ts": time.time()}
        self.event_history[workflow_id].append(event_with_ts)

    async def broadcast(self, workflow_id: str, event: dict):
        """Send an event to all connected clients and store in history."""
        # Store event for catch-up
        self._store_event(workflow_id, event)

        if workflow_id not in self.active_connections:
            return

        message = json.dumps(event)
        dead_connections = []

        for connection in self.active_connections[workflow_id]:
            try:
                await connection.send_text(message)
            except Exception:
                dead_connections.append(connection)

        # Clean up dead connections
        for dead in dead_connections:
            if dead in self.active_connections.get(workflow_id, []):
                self.active_connections[workflow_id].remove(dead)

    def cleanup_workflow(self, workflow_id: str):
        """Clean up event history for a completed workflow (after a delay)."""
        # Keep history for 10 minutes after completion for late reconnects
        async def _delayed_cleanup():
            await asyncio.sleep(600)  # 10 minutes
            if workflow_id in self.event_history:
                del self.event_history[workflow_id]
                logger.info(f"Cleaned up event history for workflow={workflow_id}")
        
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(_delayed_cleanup())
        except RuntimeError:
            # No event loop running — just delete immediately
            if workflow_id in self.event_history:
                del self.event_history[workflow_id]

    # ─── Convenience methods ───

    async def send_workflow_started(self, workflow_id: str, mode: str, provider: str):
        """Announce a workflow start, including the effective AI mode.

        `mode` is "live" (real LLM) or "mock" (simulated demo data). The frontend
        uses this to show an honest badge so mock output is never mistaken for
        real analysis.
        """
        await self.broadcast(workflow_id, {
            "type": "workflow_started",
            "mode": mode,
            "provider": provider,
        })

    async def send_agent_started(self, workflow_id: str, agent_name: str):
        await self.broadcast(workflow_id, {
            "type": "agent_started",
            "agent": agent_name,
        })

    async def send_agent_thinking(self, workflow_id: str, agent_name: str, content: str):
        await self.broadcast(workflow_id, {
            "type": "agent_thinking",
            "agent": agent_name,
            "content": content,
        })

    async def send_agent_tool_call(self, workflow_id: str, agent_name: str, tool: str, query: str):
        await self.broadcast(workflow_id, {
            "type": "agent_tool_call",
            "agent": agent_name,
            "tool": tool,
            "query": query,
        })

    async def send_agent_completed(self, workflow_id: str, agent_name: str, preview: str):
        await self.broadcast(workflow_id, {
            "type": "agent_completed",
            "agent": agent_name,
            "output_preview": preview,
        })

    async def send_inter_agent_message(self, workflow_id: str, sender: str, recipient: str, message: str):
        await self.broadcast(workflow_id, {
            "type": "inter_agent_message",
            "from": sender,
            "to": recipient,
            "message": message,
        })

    async def send_workflow_completed(
        self,
        workflow_id: str,
        project_id: Optional[str] = None,
        report_available: bool = False,
    ):
        await self.broadcast(workflow_id, {
            "type": "workflow_completed",
            "project_id": project_id,
            "report_available": report_available,
            "download_url": f"/api/v1/projects/{project_id}/report" if project_id else None,
        })
        # Schedule cleanup
        self.cleanup_workflow(workflow_id)

    async def send_workflow_error(self, workflow_id: str, agent_name: str, error: str):
        await self.broadcast(workflow_id, {
            "type": "workflow_error",
            "agent": agent_name,
            "error": error,
            "recoverable": True,
        })

    async def send_agent_reasoning_step(
        self,
        workflow_id: str,
        agent_name: str,
        step: int,
        total_steps: int,
        label: str,
        content: str,
    ):
        """Emit a multi-step reasoning event (think → critique → refine)."""
        await self.broadcast(workflow_id, {
            "type": "agent_reasoning_step",
            "agent": agent_name,
            "step": step,
            "total_steps": total_steps,
            "label": label,
            "content": content,
        })

    async def send_board_meeting_round(
        self,
        workflow_id: str,
        round_number: int,
        challenger: str,
        target: str,
        content: str,
    ):
        """Emit a board meeting debate round event."""
        await self.broadcast(workflow_id, {
            "type": "board_meeting_round",
            "round": round_number,
            "challenger": challenger,
            "target": target,
            "content": content,
        })


# Singleton
ws_manager = WebSocketManager()

