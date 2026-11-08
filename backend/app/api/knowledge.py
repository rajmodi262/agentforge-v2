"""AgentForge AI — Knowledge Base API (Phase 3)

Full RAG knowledge management with DB persistence:
- Document upload (PDF, MD, TXT)
- Intelligent chunking and embedding
- Hybrid search (vector + keyword)
- Knowledge base statistics
"""

import uuid
import os
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, UploadFile, File, Query, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.models.db_models import KnowledgeDocument
from app.api.auth import get_current_user

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"], dependencies=[Depends(get_current_user)])

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "knowledge_store")


def _ensure_upload_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    project_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Upload a document to the knowledge base.
    
    Supports PDF, Markdown, and plain text files.
    Documents are chunked and embedded for RAG retrieval.
    Metadata persisted in DB; files on disk; embeddings in ChromaDB.
    """
    allowed = {".pdf", ".md", ".txt", ".docx", ".csv"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed:
        raise HTTPException(400, f"File type '{ext}' not supported. Use: {allowed}")

    _ensure_upload_dir()

    # Save file
    doc_id = str(uuid.uuid4())
    save_path = os.path.join(UPLOAD_DIR, f"{doc_id}{ext}")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 10 MB)")
    with open(save_path, "wb") as f:
        f.write(content)

    # Extract text
    text = ""
    if ext in {".md", ".txt", ".csv"}:
        text = content.decode("utf-8", errors="replace")
    elif ext == ".pdf":
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=content, filetype="pdf")
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
        except ImportError:
            text = f"[PDF content - {len(content)} bytes - install PyMuPDF for extraction]"
    elif ext == ".docx":
        text = f"[DOCX content - {len(content)} bytes]"

    # Chunk the text
    chunks = _chunk_text(text, chunk_size=500, overlap=50)

    # Store in RAG
    stored_count = 0
    try:
        from app.services.rag_service import _get_collection
        collection = _get_collection()
        if collection:
            for i, chunk in enumerate(chunks):
                chunk_id = f"{doc_id}_chunk_{i}"
                collection.upsert(
                    ids=[chunk_id],
                    documents=[chunk],
                    metadatas=[{
                        "document_id": doc_id,
                        "filename": file.filename,
                        "chunk_index": i,
                        "project_id": project_id or "",
                        "source": "knowledge",
                    }],
                )
                stored_count += 1
    except Exception as e:
        logger.warning(f"RAG storage failed: {e}")

    # Persist document metadata in DB (survives restarts)
    doc_record = KnowledgeDocument(
        id=uuid.UUID(doc_id),  # same id as the RAG chunk ids, so delete can find them
        filename=file.filename,
        file_size=len(content),
        extension=ext,
        chunks=len(chunks),
        stored_in_rag=stored_count,
        project_id=project_id,
        file_path=save_path,
    )
    db.add(doc_record)
    db.commit()
    db.refresh(doc_record)

    return {
        "document_id": str(doc_record.id),
        "filename": file.filename,
        "chunks_created": len(chunks),
        "chunks_embedded": stored_count,
        "status": "success",
    }


@router.get("/documents")
async def list_documents(
    project_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List all uploaded documents."""
    q = db.query(KnowledgeDocument)
    if project_id:
        q = q.filter(KnowledgeDocument.project_id == project_id)
    docs = q.order_by(KnowledgeDocument.created_at.desc()).all()
    return {"total": len(docs), "documents": [d.to_dict() for d in docs]}


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, db: Session = Depends(get_db)):
    """Remove a document from the knowledge base."""
    doc = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.id == doc_id
    ).first()
    if not doc:
        raise HTTPException(404, "Document not found")

    # Remove from RAG
    try:
        from app.services.rag_service import _get_collection
        collection = _get_collection()
        if collection:
            chunk_ids = [f"{doc_id}_chunk_{i}" for i in range(doc.chunks)]
            collection.delete(ids=chunk_ids)
    except Exception as e:
        logger.warning(f"RAG deletion failed: {e}")

    # Remove file from disk
    if doc.file_path and os.path.exists(doc.file_path):
        try:
            os.remove(doc.file_path)
        except OSError:
            pass

    # Remove from DB
    db.delete(doc)
    db.commit()

    return {"status": "deleted", "document_id": doc_id}


@router.post("/search")
async def search_knowledge(
    query: str = Query(..., min_length=3),
    n_results: int = Query(5, le=20),
    project_id: Optional[str] = None,
):
    """Search the knowledge base using semantic similarity."""
    from app.services.rag_service import retrieve_similar_context

    results = retrieve_similar_context(
        query=query,
        project_id=project_id,
        n_results=n_results,
    )

    return {
        "query": query,
        "results_count": len(results),
        "results": results,
    }


@router.get("/stats")
async def knowledge_stats(db: Session = Depends(get_db)):
    """Knowledge base statistics."""
    from app.services.rag_service import get_rag_status
    from sqlalchemy import func

    rag = get_rag_status()
    total_docs = db.query(func.count(KnowledgeDocument.id)).scalar() or 0
    total_chunks = db.query(func.sum(KnowledgeDocument.chunks)).scalar() or 0

    return {
        "total_documents": total_docs,
        "total_chunks": total_chunks,
        "rag_status": rag,
        "supported_formats": [".pdf", ".md", ".txt", ".docx", ".csv"],
    }


def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list:
    """Split text into overlapping chunks for embedding."""
    if not text:
        return []

    words = text.split()
    chunks = []
    start = 0

    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        if chunk.strip():
            chunks.append(chunk)
        start = end - overlap

    return chunks if chunks else [text[:2000]]
