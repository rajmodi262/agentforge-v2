"""AgentForge AI — LangGraph Workflow Engine (v2: Parallel + Board Meeting)

Production-grade multi-agent orchestrator with:
- Parallel fan-out/fan-in execution (Marketing, Developer, Finance run simultaneously)
- Board Meeting debate node (agents challenge each other before report compilation)
- Multi-step reasoning (think → critique → refine) on key agents
- Deterministic, inspectable execution flow via LangGraph StateGraph
- Full WebSocket streaming + DB persistence at each node boundary

Graph topology:

  START → CEO → Research → [Marketing ‖ Developer] → Finance → Analytics → Operations
        → Board Meeting → Synthesis → Report → END
"""

import os
import time
import uuid
import asyncio
import logging
from typing import TypedDict, Optional, Dict, Any, List, Annotated
from datetime import datetime, timezone
import operator

from langgraph.graph import StateGraph, START, END
from sqlalchemy.orm import Session, sessionmaker

from app.database import get_session_factory
from app.models.db_models import WorkflowRun, AgentTask, AgentMessage, Project, ProjectReport
from app.services.websocket_manager import ws_manager

from app.agents.ceo_agent import CEOAgent
from app.agents.research_agent import ResearchAgent
from app.agents.marketing_agent import MarketingAgent
from app.agents.developer_agent import DeveloperAgent
from app.agents.finance_agent import FinanceAgent
from app.agents.analytics_agent import AnalyticsAgent
from app.agents.operations_agent import OperationsAgent
from app.agents.report_compiler import ReportCompiler

logger = logging.getLogger(__name__)

# Ensure report output directory exists
REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "generated_reports")
os.makedirs(REPORTS_DIR, exist_ok=True)


# ─────────────────────────── State Schema ───────────────────────────

def _merge_dicts(existing: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """Reducer: merge new keys into existing dict (non-destructive)."""
    merged = {**existing}
    merged.update(new)
    return merged


class WorkflowState(TypedDict):
    """Shared state passed through the entire LangGraph execution.
    
    Each agent node reads from this state and returns updates.
    The `agent_outputs` dict uses a custom reducer to merge results
    from each node without overwriting previous agent outputs.
    """
    # Inputs (set once at start, read-only after)
    workflow_id: str
    project_id: str
    brief: str
    target_market: Optional[str]
    budget_range: Optional[str]

    # Accumulated context — each agent appends its output
    agent_outputs: Annotated[Dict[str, Any], _merge_dicts]

    # Tracking
    completed_agents: Annotated[list, operator.add]
    total_tokens: Annotated[int, operator.add]
    total_cost: Annotated[float, operator.add]
    error_messages: Annotated[list, operator.add]

    # Report path (set by final node)
    report_path: Optional[str]

    # Injected dependencies (not serialized)
    session_factory: Optional[Any]


# ─────────────────────── DB helpers (run via asyncio.to_thread) ───────────────────────
# These wrap blocking SQLAlchemy work so it never runs on the event loop. Each
# helper opens, uses, and closes its OWN session, so nothing is shared across
# threads — safe under the parallel fan-out of agent nodes.

def _db_create_agent_task(factory, task_id, workflow_id, agent_name):
    db: Session = factory()
    try:
        db.add(AgentTask(
            id=task_id,
            workflow_id=workflow_id,
            agent_name=agent_name,
            status="running",
            started_at=datetime.now(timezone.utc),
        ))
        db.commit()
    finally:
        db.close()


def _db_record_handoff(factory, workflow_id, sender, recipient):
    db: Session = factory()
    try:
        db.add(AgentMessage(
            workflow_id=workflow_id,
            sender=sender,
            recipient=recipient,
            message_type="data",
            content=f"Passing {sender} analysis to {recipient} for cross-referencing.",
        ))
        db.commit()
    finally:
        db.close()


def _db_complete_agent_task(factory, task_id, output_data, tokens_used, execution_time):
    db: Session = factory()
    try:
        task = db.query(AgentTask).filter(AgentTask.id == task_id).first()
        if task:
            task.status = "completed"
            task.output_data = output_data
            task.tokens_used = tokens_used
            task.execution_time = execution_time
            task.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


def _db_fail_agent_task(factory, task_id):
    db: Session = factory()
    try:
        task = db.query(AgentTask).filter(AgentTask.id == task_id).first()
        if task:
            task.status = "failed"
            task.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


def _store_rag(project_id, agent_name, output, workflow_id):
    from app.services.rag_service import store_agent_output
    store_agent_output(
        project_id=project_id,
        agent_name=agent_name,
        output=output,
        workflow_id=workflow_id,
    )


def _retrieve_rag(query, project_id, workflow_id) -> str:
    """Fetch grounding context: uploaded knowledge-base docs + this project's past runs.

    Best-effort: returns "" if the vector store is unavailable or nothing relevant matches.
    Excludes the current workflow so an agent never reads its own siblings.
    """
    try:
        from app.services.rag_service import retrieve_similar_context, retrieve_knowledge
        sections = []
        knowledge = retrieve_knowledge(query=query, project_id=project_id, n_results=3)
        if knowledge:
            sections.append("KNOWLEDGE BASE (uploaded documents):\n" + "\n\n".join(
                f"[{k['metadata'].get('filename', 'document')}] {k['document'][:800]}" for k in knowledge
            ))
        past = retrieve_similar_context(
            query=query,
            project_id=project_id,
            n_results=3,
            exclude_workflow_id=workflow_id,
        )
        past = [r for r in past if r.get("document")]
        if past:
            sections.append("PAST ANALYSES OF THIS PROJECT:\n" + "\n\n".join(r["document"][:800] for r in past))
        return "\n\n".join(sections)
    except Exception as e:
        logger.debug(f"RAG retrieve skipped: {e}")
        return ""


def _build_and_persist_report(factory, project_id, brief, agent_outputs):
    compiler = ReportCompiler()
    context = {"brief": brief}
    context.update(agent_outputs)

    report_json = compiler.compile_json(context)
    report_filename = f"AgentForge_Report_{project_id[:8]}_{int(time.time())}.pdf"
    absolute_path = os.path.join(REPORTS_DIR, report_filename)
    actual_path = compiler.generate_pdf(report_json, absolute_path)

    file_size = os.path.getsize(actual_path) if os.path.exists(actual_path) else 0
    db: Session = factory()
    try:
        db.add(ProjectReport(
            project_id=project_id,
            file_path=report_filename,
            file_size=file_size,
        ))
        db.commit()
    finally:
        db.close()
    return actual_path


def _db_mark_workflow_running(factory, workflow_id) -> bool:
    db: Session = factory()
    try:
        wf = db.query(WorkflowRun).filter(WorkflowRun.id == workflow_id).first()
        if not wf:
            return False
        wf.status = "running"
        wf.started_at = datetime.now(timezone.utc)
        db.commit()
        return True
    finally:
        db.close()


def _db_finalize_workflow(factory, workflow_id, project_id, total_tokens, total_cost, error_messages):
    db: Session = factory()
    try:
        wf = db.query(WorkflowRun).filter(WorkflowRun.id == workflow_id).first()
        if wf:
            wf.status = "completed"
            wf.completed_at = datetime.now(timezone.utc)
            wf.total_tokens = total_tokens
            wf.total_cost = total_cost
            if error_messages:
                wf.error_message = "; ".join(error_messages)
        project = db.query(Project).filter(Project.id == project_id).first()
        if project:
            project.status = "completed"
        db.commit()
    finally:
        db.close()


def _db_mark_workflow_failed(factory, workflow_id, project_id, error):
    db: Session = factory()
    try:
        wf = db.query(WorkflowRun).filter(WorkflowRun.id == workflow_id).first()
        if wf:
            wf.status = "failed"
            wf.error_message = error
            wf.completed_at = datetime.now(timezone.utc)
        project = db.query(Project).filter(Project.id == project_id).first()
        if project:
            project.status = "error"
        db.commit()
    finally:
        db.close()


# ─────────────────────────── Node Functions ───────────────────────────

def _make_agent_node(agent_key: str, AgentClass):
    """Factory: creates a LangGraph node function for a given agent.
    
    Each node:
    1. Creates the agent instance
    2. Builds the context from accumulated agent_outputs
    3. Runs the agent with WebSocket streaming
    4. Persists the AgentTask to DB
    5. Returns state updates
    """

    async def node_fn(state: WorkflowState) -> dict:
        agent = AgentClass()
        workflow_id = state["workflow_id"]
        factory = state.get("session_factory") or get_session_factory()

        # Build context from accumulated outputs (no DB / no I/O)
        context = {"brief": state["brief"]}
        context.update(state.get("agent_outputs", {}))

        # Build full brief
        brief = state["brief"]
        if state.get("target_market"):
            brief += f"\nTarget Market: {state['target_market']}"
        if state.get("budget_range"):
            brief += f"\nBudget Range: {state['budget_range']}"

        # Mint the task id up front so we can update it later without a shared session
        task_id = uuid.uuid4()

        try:
            # Create DB task record (offloaded — never blocks the event loop)
            await asyncio.to_thread(_db_create_agent_task, factory, task_id, workflow_id, agent.name)

            # Send inter-agent handoff message
            completed = state.get("completed_agents", [])
            if completed:
                prev_name = completed[-1]
                await asyncio.to_thread(_db_record_handoff, factory, workflow_id, prev_name, agent.name)
                await ws_manager.send_inter_agent_message(
                    workflow_id, prev_name, agent.name,
                    f"Handing off to {agent.name}..."
                )

            # RAG enrichment: pull similar past analyses into the brief (offloaded)
            retrieved = await asyncio.to_thread(
                _retrieve_rag, brief, state["project_id"], workflow_id
            )
            if retrieved:
                brief = f"{brief}\n\nRETRIEVED CONTEXT (RAG — use where relevant):\n{retrieved}"
                sources = [s for s in ("KNOWLEDGE BASE", "PAST ANALYSES") if s in retrieved]
                await ws_manager.send_agent_tool_call(
                    workflow_id, agent.name, "rag_retrieval",
                    f"Retrieved context from: {', '.join(sources)}",
                )

            # Run the agent
            result = await agent.run(
                brief=brief,
                context=context,
                workflow_id=workflow_id,
            )

            # Update DB task (offloaded)
            await asyncio.to_thread(
                _db_complete_agent_task, factory, task_id,
                result["output"], result["tokens_used"], result["execution_time"],
            )

            # Store in RAG pipeline for future context enrichment (blocking I/O — offloaded)
            try:
                await asyncio.to_thread(
                    _store_rag, state["project_id"], agent.name, result["output"], workflow_id
                )
            except Exception as rag_err:
                logger.debug(f"RAG store skipped: {rag_err}")

            logger.info(f"[LangGraph] Node '{agent_key}' completed: {result['tokens_used']} tokens")

            return {
                "agent_outputs": {f"{agent_key}_output": result["output"]},
                "completed_agents": [agent.name],
                "total_tokens": result["tokens_used"],
                "total_cost": result["cost"],
            }

        except Exception as e:
            logger.error(f"[LangGraph] Node '{agent_key}' failed: {e}")
            await asyncio.to_thread(_db_fail_agent_task, factory, task_id)
            await ws_manager.send_workflow_error(workflow_id, agent.name, str(e))

            return {
                "agent_outputs": {f"{agent_key}_output": {"error": str(e)}},
                "completed_agents": [agent.name],
                "error_messages": [f"{agent.name}: {str(e)}"],
            }

    # Set the function name for LangGraph's internal tracking
    node_fn.__name__ = f"node_{agent_key}"
    return node_fn


async def synthesis_node(state: WorkflowState) -> dict:
    """Editor stage: weave specialists + board debate into one coherent blueprint."""
    workflow_id = state["workflow_id"]
    from app.agents.synthesizer import synthesize_blueprint
    from app.services.claude_service import get_claude_service

    try:
        await ws_manager.send_agent_started(workflow_id, "Chief Synthesizer")
        await ws_manager.send_agent_thinking(
            workflow_id, "Chief Synthesizer",
            "Synthesizing all specialist analyses and the board debate into one coherent blueprint..."
        )
        synth = await synthesize_blueprint(
            state["brief"], state.get("agent_outputs", {}), get_claude_service(),
            workflow_id=workflow_id,
        )
        await ws_manager.send_agent_completed(
            workflow_id, "Chief Synthesizer", "Final blueprint synthesized from all agents"
        )
        return {
            "agent_outputs": {"final_blueprint_output": synth["blueprint"]},
            "completed_agents": ["Chief Synthesizer"],
            "total_tokens": synth.get("tokens_used", 0),
        }
    except Exception as e:
        logger.error(f"[LangGraph] Synthesis node failed: {e}")
        return {"agent_outputs": {"final_blueprint_output": {"error": str(e)}}}


async def report_node(state: WorkflowState) -> dict:
    """Final node: compiles all agent outputs into a PDF report."""
    workflow_id = state["workflow_id"]
    project_id = state["project_id"]
    factory = state.get("session_factory") or get_session_factory()

    try:
        await ws_manager.send_agent_thinking(
            workflow_id, "Report Compiler",
            "Compiling all agent outputs into final report..."
        )

        # PDF generation + DB persist are blocking — offload to a worker thread
        actual_path = await asyncio.to_thread(
            _build_and_persist_report,
            factory, project_id, state["brief"], state.get("agent_outputs", {}),
        )

        logger.info(f"[LangGraph] Report generated: {actual_path}")
        return {"report_path": actual_path}

    except Exception as e:
        logger.error(f"[LangGraph] Report generation failed: {e}")
        return {"error_messages": [f"Report: {str(e)}"]}


# ─────────────────────────── Graph Construction ───────────────────────────

# Agent pipeline definition
AGENT_PIPELINE = [
    ("ceo", CEOAgent),
    ("research", ResearchAgent),
    ("marketing", MarketingAgent),
    ("developer", DeveloperAgent),
    ("finance", FinanceAgent),
    ("analytics", AnalyticsAgent),
    ("operations", OperationsAgent),
]



def build_workflow_graph() -> StateGraph:
    """Construct the AgentForge 9-node LangGraph with parallel execution.
    
    Graph topology (dependency-ordered, with parallel fan-out/fan-in):

        START → ceo → research → ┬─ marketing ─┐
                                 └─ developer ─┘ → finance → analytics → operations
              → board_meeting → synthesis → report → END

    - Edges follow each agent's `required_context_keys`, so every agent
      actually receives the upstream outputs its prompt relies on
    - Marketing and Developer run in PARALLEL (both need only CEO + Research)
    - Finance waits for both (fan-in) so it can use real pricing + infra costs
    - Board Meeting debates all outputs; Synthesis merges them; Report builds the PDF

    The `_merge_dicts` reducer on `agent_outputs` handles concurrent writes
    safely — each agent writes to a unique key (e.g., `marketing_output`).
    """
    from app.agents.board_meeting import board_meeting_node

    graph = StateGraph(WorkflowState)

    # Add agent nodes
    for agent_key, AgentClass in AGENT_PIPELINE:
        graph.add_node(agent_key, _make_agent_node(agent_key, AgentClass))

    # Add board meeting debate node
    graph.add_node("board_meeting", board_meeting_node)

    # Add synthesis (editor) node — coherent blueprint from all agents + debate
    graph.add_node("synthesis", synthesis_node)

    # Add report compiler node
    graph.add_node("report", report_node)

    # ─── Edges: Sequential lead-in ───
    graph.add_edge(START, "ceo")

    # Research runs next: every downstream specialist needs market context
    graph.add_edge("ceo", "research")

    # ─── Edges: Parallel fan-out (research → marketing + developer) ───
    # Both consume CEO + Research output and don't depend on each other.
    graph.add_edge("research", "marketing")
    graph.add_edge("research", "developer")

    # ─── Edges: Fan-in (marketing + developer → finance) ───
    # Native LangGraph fan-in: finance waits for BOTH, so it can price and cost
    # the plan using the real GTM pricing and infrastructure estimates.
    graph.add_edge(["marketing", "developer"], "finance")
    graph.add_edge("finance", "analytics")

    # ─── Edges: Sequential tail ───
    graph.add_edge("analytics", "operations")
    graph.add_edge("operations", "board_meeting")
    graph.add_edge("board_meeting", "synthesis")
    graph.add_edge("synthesis", "report")
    graph.add_edge("report", END)

    return graph


# Compile once at module level — reusable across all workflow invocations
workflow_graph = build_workflow_graph().compile()


# ─────────────────────────── Entrypoint ───────────────────────────

async def run_workflow(
    workflow_id: str,
    project_id: str,
    business_idea: str,
    target_market: Optional[str] = None,
    budget_range: Optional[str] = None,
    session_factory: Optional[sessionmaker] = None,
):
    """Run the full 7-agent LangGraph pipeline.
    
    This function is called as a BackgroundTask from the API.
    It invokes the compiled LangGraph, which handles the sequential
    execution of all agent nodes + report generation.
    """
    factory = session_factory or get_session_factory()

    try:
        # Mark workflow as running (offloaded)
        found = await asyncio.to_thread(_db_mark_workflow_running, factory, workflow_id)
        if not found:
            logger.error(f"Workflow {workflow_id} not found in database")
            return

        # Announce the effective AI mode up front so the UI can badge mock runs honestly.
        # verify_provider() pings the key so a revoked/invalid key degrades to mock truthfully.
        from app.services.claude_service import get_claude_service
        mode = await get_claude_service().verify_provider()
        await ws_manager.send_workflow_started(workflow_id, mode["mode"], mode["provider"])
        logger.info(f"[LangGraph] Workflow {workflow_id} running in {mode['mode']} mode (provider={mode['provider']})")

        # Build initial state
        initial_state: WorkflowState = {
            "workflow_id": workflow_id,
            "project_id": project_id,
            "brief": business_idea,
            "target_market": target_market,
            "budget_range": budget_range,
            "agent_outputs": {},
            "completed_agents": [],
            "total_tokens": 0,
            "total_cost": 0.0,
            "error_messages": [],
            "report_path": None,
            "session_factory": factory,
        }

        # Execute the LangGraph
        logger.info(f"[LangGraph] Starting workflow {workflow_id}")
        final_state = await workflow_graph.ainvoke(initial_state)

        # Persist completion (workflow + project) — offloaded
        await asyncio.to_thread(
            _db_finalize_workflow, factory, workflow_id, project_id,
            final_state.get("total_tokens", 0),
            final_state.get("total_cost", 0.0),
            final_state.get("error_messages"),
        )

        # Notify frontend
        await ws_manager.send_workflow_completed(
            workflow_id,
            project_id=project_id,
            report_available=final_state.get("report_path") is not None,
        )

        completed_count = len(final_state.get("completed_agents", []))
        logger.info(
            f"[LangGraph] Workflow {workflow_id} completed: "
            f"{final_state.get('total_tokens', 0)} tokens, "
            f"${final_state.get('total_cost', 0.0):.4f}, "
            f"{completed_count}/8 agents (incl. Board Meeting)"
        )

    except Exception as e:
        logger.error(f"[LangGraph] Workflow {workflow_id} failed: {e}", exc_info=True)
        await asyncio.to_thread(_db_mark_workflow_failed, factory, workflow_id, project_id, str(e))
        await ws_manager.send_workflow_error(workflow_id, "LangGraph Orchestrator", str(e))
