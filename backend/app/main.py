"""AgentForge AI — FastAPI Main Application

Production hardened:
- Request ID middleware for end-to-end tracing
- Rate limiting with proper error handling
- Trusted host protection
- Health endpoint with full system diagnostics

Note: Background tasks (orchestrator) handle their own DB errors internally.
App-level exception handlers are intentionally limited to request-scoped errors
to avoid conflicts with BackgroundTask lifecycle.
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import get_settings
from app.database import init_db, SessionLocal
from app.api.router import api_router
from app.rate_limiter import limiter
from app.middleware.request_id import RequestIDMiddleware
from app.middleware.audit import AuditMiddleware
from app.services.claude_service import get_claude_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown events."""
    init_db()
    logger.info(f"AgentForge AI started (mock_mode={settings.mock_mode})")
    yield
    logger.info("AgentForge AI shutting down")


app = FastAPI(
    title="AgentForge AI",
    description="Multi-agent AI orchestration for startup business planning",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ─── Middleware stack (order matters: last added = first executed) ───

# Request ID tracing — runs first on every request
app.add_middleware(RequestIDMiddleware)

# Audit trail — logs all mutating API calls
app.add_middleware(AuditMiddleware)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Trusted hosts — prevent host header attacks
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "*.agentforge.ai", "testserver"],
)

# CORS — specific origins, not wildcard
ALLOWED_ORIGINS = [
    settings.frontend_url,
    "http://localhost:5180",   # AgentForge dedicated dev port
    "http://127.0.0.1:5180",
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],  # Allow frontend to read request ID
)

# Include API routes
app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "service": "AgentForge AI",
        "version": "1.0.0",
        "status": "running",
        "mock_mode": get_claude_service().mock_mode,
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    """Detailed health check for monitoring and demo presentations."""
    # Check DB connection
    db_status = "connected"
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
    except Exception as e:
        db_status = f"error: {str(e)[:50]}"

    # Check AI provider
    ai_svc = get_claude_service()

    # Check RAG pipeline
    from app.services.rag_service import get_rag_status
    rag_status = get_rag_status()

    # Check n8n integration
    from app.services.n8n_service import get_n8n_service
    n8n_svc = get_n8n_service()

    return {
        "status": "healthy",
        "version": "1.0.0",
        "database": db_status,
        # Effective runtime mode (reflects silent fallback to mock when no key/client),
        # not just the configured flag — this is what actually runs.
        "mock_mode": ai_svc.mock_mode if hasattr(ai_svc, 'mock_mode') else settings.mock_mode,
        "configured_mock_mode": settings.mock_mode,
        "ai_provider": ai_svc.provider if hasattr(ai_svc, 'provider') else "unknown",
        "orchestration_engine": "LangGraph",
        "rag_pipeline": rag_status,
        "code_sandbox": {"enabled": True, "language": "python", "timeout_seconds": 10},
        "n8n_integration": {"enabled": n8n_svc.enabled, "webhooks": len(n8n_svc._webhooks)},
        "docs": "/docs",
    }

