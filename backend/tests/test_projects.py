import pytest
"""Tests for Projects API endpoints."""


def test_create_project_authenticated(client, auth_headers):
    """Test creating a project with auth."""
    response = client.post("/api/v1/projects/", json={
        "title": "My Startup",
        "business_idea": "An AI-powered tool for resume screening and matching",
        "target_market": "India",
        "budget_range": "₹0-₹50K",
    }, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "My Startup"
    assert data["status"] == "draft"
    assert "id" in data


def test_create_project_unauthenticated(client):
    """Test creating a project without auth (demo mode — should still work)."""
    response = client.post("/api/v1/projects/", json={
        "title": "Demo Project",
        "business_idea": "A platform for connecting freelancers with small businesses",
    })
    assert response.status_code == 200  # Demo user is created automatically


def test_list_projects_authenticated(client, auth_headers):
    """Test listing projects requires auth."""
    # Create a project first
    client.post("/api/v1/projects/", json={
        "title": "Project 1",
        "business_idea": "First test project for listing functionality",
    }, headers=auth_headers)

    response = client.get("/api/v1/projects/", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert len(data["projects"]) >= 1


def test_list_projects_unauthenticated(client):
    """Test listing projects without auth returns 401."""
    response = client.get("/api/v1/projects/")
    assert response.status_code == 401


def test_get_project_by_id(client, auth_headers, test_project):
    """Test getting a project by ID."""
    project_id = test_project["id"]
    response = client.get(f"/api/v1/projects/{project_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["id"] == project_id


def test_get_project_not_found(client, auth_headers):
    """Test getting a non-existent project returns 404."""
    response = client.get(
        "/api/v1/projects/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_create_project_short_idea(client, auth_headers):
    """Test that very short business ideas are rejected."""
    response = client.post("/api/v1/projects/", json={
        "title": "Bad",
        "business_idea": "short",  # Less than 10 chars
    }, headers=auth_headers)
    assert response.status_code == 422


def test_create_project_html_sanitized(client, auth_headers):
    """Test that HTML in business idea is stripped."""
    response = client.post("/api/v1/projects/", json={
        "title": "Sanitize Test",
        "business_idea": "An app for <script>alert('xss')</script> managing team tasks and projects efficiently",
    }, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "<script>" not in data["business_idea"]


@pytest.fixture
def stub_workflow(monkeypatch):
    """The /start tests check the HTTP contract only (orchestration is covered in test_orchestrator).
    A real background workflow would outlive the test and race the next test's table drop on the
    shared in-memory SQLite connection, so record the call instead of running it."""
    calls = []

    async def _fake_run_workflow(**kwargs):
        calls.append(kwargs)
    monkeypatch.setattr("app.api.projects.run_workflow", _fake_run_workflow)
    return calls


def test_start_workflow(client, auth_headers, test_project, stub_workflow):
    """Test starting a workflow for a project."""
    project_id = test_project["id"]
    response = client.post(
        f"/api/v1/projects/{project_id}/start",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "workflow_id" in data
    assert "websocket_url" in data
    assert stub_workflow and stub_workflow[0]["project_id"] == project_id


def test_start_workflow_already_running(client, auth_headers, test_project, db_session, stub_workflow):
    """Test that starting a workflow while status is 'running' returns 400.
    
    In mock mode the background task completes nearly instantly, so we
    manually force the project into 'running' state to test the guard.
    """
    from app.models.db_models import Project
    project_id = test_project["id"]

    # Start the workflow once (this may complete instantly in mock mode)
    first = client.post(f"/api/v1/projects/{project_id}/start", headers=auth_headers)
    assert first.status_code == 200

    # Force the project back to 'running' to simulate an in-progress workflow
    project = db_session.query(Project).filter(Project.id == project_id).first()
    project.status = "running"
    db_session.commit()

    # Second start should be rejected
    response = client.post(f"/api/v1/projects/{project_id}/start", headers=auth_headers)
    assert response.status_code == 400
    assert "already running" in response.json()["detail"].lower()
