"""AgentForge AI — Test Fixtures

Shared fixtures for all test modules:
- In-memory SQLite database with StaticPool (shared across connections)
- FastAPI TestClient
- Auth helper (create user, get token)
"""

import os
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Force mock mode + SQLite for tests
os.environ["MOCK_MODE"] = "true"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-not-for-production"

from fastapi.testclient import TestClient
from app.database import Base, get_db
from app.main import app
from app.rate_limiter import limiter

# Disable rate limiting during tests
limiter.enabled = False


# In-memory SQLite with StaticPool — all connections share the same DB
test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

# Enable foreign keys for SQLite
@event.listens_for(test_engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_database():
    """Create fresh tables before each test, drop after."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def db_session():
    """Raw DB session for direct model testing."""
    db = TestSessionLocal()
    yield db
    db.close()


@pytest.fixture
def auth_headers(client):
    """Register a test user and return auth headers."""
    response = client.post("/api/v1/auth/register", json={
        "email": "test@agentforge.ai",
        "password": "TestPass123",
        "name": "Test User",
    })
    assert response.status_code == 200, f"Registration failed: {response.text}"
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def test_project(client, auth_headers):
    """Create a test project and return it."""
    response = client.post("/api/v1/projects/", json={
        "title": "Test Project",
        "business_idea": "An AI-powered tool for automated testing of web applications",
        "target_market": "India",
        "budget_range": "₹0-₹50K",
    }, headers=auth_headers)
    assert response.status_code == 200
    return response.json()


@pytest.fixture(autouse=True)
def _no_live_web_search(monkeypatch):
    """Keep the suite off the network: live Wikipedia search returns no results."""
    from app.tools import web_search as web_search_module

    async def _offline(query, count):
        return []
    monkeypatch.setattr(web_search_module, "_wikipedia_search", _offline)
