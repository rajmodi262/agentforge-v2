"""AgentForge AI — RAG Service (ChromaDB Vector Store)

Provides Retrieval-Augmented Generation capabilities:
- Stores agent outputs as embeddings in ChromaDB
- Retrieves relevant context from past analyses
- Enriches new agent runs with historical knowledge
"""

import logging
import hashlib
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Lazy-init to avoid import cost when RAG isn't used
_client = None
_collection = None


def _get_collection():
    """Lazy-initialize ChromaDB collection with PERSISTENT storage."""
    global _client, _collection
    if _collection is None:
        try:
            import chromadb
            from chromadb.config import Settings
            import os
            # chromadb 0.5.x has a posthog telemetry bug that logs noisy
            # "capture() takes 1 positional argument" ERRORs regardless of the
            # anonymized_telemetry setting. Mute that logger — purely cosmetic.
            logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)
            persist_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "chroma_data")
            os.makedirs(persist_dir, exist_ok=True)
            # anonymized_telemetry=False silences the noisy posthog "capture()" error logs
            _client = chromadb.PersistentClient(
                path=persist_dir,
                settings=Settings(anonymized_telemetry=False),
            )
            _collection = _client.get_or_create_collection(
                name="agentforge_agent_outputs",
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(f"ChromaDB RAG collection initialized (persistent: {persist_dir})")
        except ImportError:
            logger.warning("ChromaDB not installed — RAG disabled")
            return None
        except Exception as e:
            logger.warning(f"ChromaDB init failed: {e} — RAG disabled")
            return None
    return _collection


def store_agent_output(
    project_id: str,
    agent_name: str,
    output: Dict[str, Any],
    workflow_id: str,
) -> bool:
    """Store an agent's output as a searchable embedding.
    
    Args:
        project_id: Project UUID
        agent_name: e.g. "CEO Agent"
        output: The agent's JSON output dict
        workflow_id: Workflow run UUID
    
    Returns:
        True if stored successfully, False otherwise
    """
    collection = _get_collection()
    if collection is None:
        return False

    try:
        import json
        # Flatten output to text for embedding
        text = f"Agent: {agent_name}\n"
        text += json.dumps(output, indent=2, default=str)

        # Truncate to avoid token limits
        if len(text) > 8000:
            text = text[:8000]

        doc_id = hashlib.md5(f"{workflow_id}:{agent_name}".encode()).hexdigest()

        collection.upsert(
            ids=[doc_id],
            documents=[text],
            metadatas=[{
                "project_id": project_id,
                "agent_name": agent_name,
                "workflow_id": workflow_id,
            }],
        )

        logger.info(f"RAG: Stored {agent_name} output for project {project_id[:8]}")
        return True

    except Exception as e:
        logger.warning(f"RAG store failed: {e}")
        return False


def retrieve_similar_context(
    query: str,
    project_id: Optional[str] = None,
    n_results: int = 3,
    exclude_workflow_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve relevant past agent outputs for context enrichment.
    
    Args:
        query: The current business idea or agent prompt
        project_id: Optional filter to same project
        n_results: Number of results to return
        exclude_workflow_id: Exclude current workflow's own outputs
    
    Returns:
        List of dicts with 'document', 'metadata', and 'distance' keys
    """
    collection = _get_collection()
    if collection is None:
        return []

    try:
        # Build where filter
        where_filter = None
        if project_id and exclude_workflow_id:
            where_filter = {
                "$and": [
                    {"project_id": project_id},
                    {"workflow_id": {"$ne": exclude_workflow_id}},
                ]
            }
        elif project_id:
            where_filter = {"project_id": project_id}

        results = collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where_filter,
        )

        enriched = []
        if results and results["documents"]:
            for i, doc in enumerate(results["documents"][0]):
                enriched.append({
                    "document": doc[:2000],  # Limit context size
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results["distances"] else 0,
                })

        logger.info(f"RAG: Retrieved {len(enriched)} relevant contexts")
        return enriched

    except Exception as e:
        logger.warning(f"RAG retrieval failed: {e}")
        return []


def retrieve_knowledge(
    query: str,
    project_id: Optional[str] = None,
    n_results: int = 3,
    max_distance: float = 0.75,
) -> List[Dict[str, Any]]:
    """Retrieve uploaded knowledge-base chunks relevant to the query.

    Matches documents uploaded for this project plus global uploads (no project).
    Chunks farther than `max_distance` (cosine) are dropped as irrelevant.
    """
    collection = _get_collection()
    if collection is None:
        return []
    scopes = [""] + ([project_id] if project_id else [])
    try:
        results = collection.query(
            query_texts=[query],
            n_results=n_results,
            where={"$and": [{"source": "knowledge"}, {"project_id": {"$in": scopes}}]},
        )
        hits = []
        if results and results["documents"]:
            for i, doc in enumerate(results["documents"][0]):
                distance = results["distances"][0][i] if results["distances"] else 0
                if distance <= max_distance:
                    hits.append({
                        "document": doc[:2000],
                        "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                        "distance": distance,
                    })
        logger.info(f"RAG: Retrieved {len(hits)} knowledge-base chunks")
        return hits
    except Exception as e:
        logger.warning(f"RAG knowledge retrieval failed: {e}")
        return []


def get_rag_status() -> Dict[str, Any]:
    """Get RAG system health status."""
    collection = _get_collection()
    if collection is None:
        return {"enabled": False, "reason": "ChromaDB unavailable"}

    try:
        count = collection.count()
        return {
            "enabled": True,
            "documents_stored": count,
            "collection": "agentforge_agent_outputs",
        }
    except Exception as e:
        return {"enabled": False, "reason": str(e)}
